"""
Document number sequences (DOMAIN_PRIMITIVES.md § 2): peek() shows the next number and writes
nothing; reserve() mints it, atomically.

The reservation is one UPDATE ... SET last_value = last_value + 1 (an F() expression), never a
read followed by a write, so two callers cannot both read N and both write N+1. The counter row is
created first with INSERT ... ON CONFLICT DO NOTHING: `SELECT ... FOR UPDATE` on an empty result
locks nothing, which is how two first callers once both minted -0001. The unique constraint
core_sequence_uq decides the race; the loser's insert does nothing and its UPDATE then waits for
the winner's row lock. This is the same on SQLite and PostgreSQL.

Gapless (§ 2.4): reserve() runs in the caller's transaction and refuses outside one. A rollback
returns the number. Gap-tolerant: the counter moves on its own short connection in autocommit, so
the row lock lasts one statement; a rollback of the caller's document burns the number.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.db.models import F
from django.utils import timezone

from core.models import Sequence
from core.registry import _PATTERN_TOKEN, registry


class NumberingError(Exception):
    code = "numbering_error"


class UnknownSeries(NumberingError):
    code = "unknown_series"


def _series(key: str):
    series = registry.numbering.get(key)
    if series is None:
        raise UnknownSeries(f"{key!r} is not a registered numbering series")
    return series


def local_date(on: date | datetime | None = None) -> date:
    """The document's issue date in the PLATFORM timezone (an instant at 23:30 local on the 31st
    belongs to that month whatever UTC says). A plain date is taken as already local."""
    if isinstance(on, datetime):
        from core.business_calendar import platform_timezone

        return timezone.localtime(on, ZoneInfo(platform_timezone())).date()
    if isinstance(on, date):
        return on
    return local_date(timezone.now())


def period_key(reset: str, on: date) -> str:
    return {
        "never": "",
        "yearly": f"{on:%Y}",
        "monthly": f"{on:%Y-%m}",
        "daily": f"{on:%Y-%m-%d}",
    }[reset]


def render(series, value: int, *, on: date, scope: str = "") -> str:
    """Width is a minimum, never a truncation: {seq:04} at 10000 renders 10000."""

    def sub(match):
        token = match.group(1)
        if token.startswith("seq"):
            return str(value).zfill(int(match.group(2) or 1))
        return {
            "PREFIX": series.prefix,
            "YYYY": f"{on:%Y}",
            "YY": f"{on:%y}",
            "MM": f"{on:%m}",
            "DD": f"{on:%d}",
            "SCOPE": scope,
        }[token]

    return _PATTERN_TOKEN.sub(sub, series.pattern)


def peek(series_key: str, *, scope: str = "", on: date | datetime | None = None) -> str:
    """The number the next reserve() would mint, absent a concurrent save. Reads only."""
    series = _series(series_key)
    day = local_date(on)
    row = (
        Sequence.objects.filter(
            series=series_key, scope_key=scope, period_key=period_key(series.reset, day)
        )
        .values_list("last_value", flat=True)
        .first()
    )
    return render(series, (row or 0) + 1, on=day, scope=scope)


def reserve(series_key: str, *, scope: str = "", on: date | datetime | None = None) -> str:
    series = _series(series_key)
    day = local_date(on)
    period = period_key(series.reset, day)
    if series.gapless:
        if not connection.in_atomic_block:
            raise NumberingError("a gapless reserve() must run inside the caller's transaction")
        value = _bump_in_transaction(series_key, scope, period)
    else:
        value = _bump_independent(series_key, scope, period)
    return render(series, value, on=day, scope=scope)


def _bump_in_transaction(series_key: str, scope: str, period: str) -> int:
    with transaction.atomic():  # a savepoint when nested; the real transaction otherwise
        # Write FIRST: on SQLite the first write takes the database write lock (and waits for it),
        # where a read-then-upgrade fails at once with "database is locked".
        Sequence.objects.bulk_create(
            [Sequence(series=series_key, scope_key=scope, period_key=period, last_value=0)],
            ignore_conflicts=True,
        )
        where = {"series": series_key, "scope_key": scope, "period_key": period}
        updated = Sequence.objects.filter(**where).update(
            last_value=F("last_value") + 1, updated_at=timezone.now()
        )
        if updated != 1:  # the row was just ensured to exist: anything else is a bug, not a retry
            raise NumberingError(f"counter row for {series_key} vanished after it was created")
        # Our own UPDATE holds the row lock until commit, so this read sees OUR value.
        return Sequence.objects.filter(**where).values_list("last_value", flat=True).get()


def _bump_independent(series_key: str, scope: str, period: str) -> int:
    """Gap-tolerant: its own connection, autocommit, one statement per step. The UPDATE ...
    RETURNING is atomic on its own, so no read-then-write window exists."""
    table = Sequence._meta.db_table
    conn = connections.create_connection(DEFAULT_DB_ALIAS)
    try:
        conn.set_autocommit(True)
        args = (series_key, scope, period)
        with conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {table} (series, scope_key, period_key, last_value, updated_at) "
                "VALUES (%s, %s, %s, 0, %s) ON CONFLICT (series, scope_key, period_key) DO NOTHING",
                [*args, timezone.now()],
            )
            cursor.execute(
                f"UPDATE {table} SET last_value = last_value + 1, updated_at = %s "
                "WHERE series = %s AND scope_key = %s AND period_key = %s RETURNING last_value",
                [timezone.now(), *args],
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    if row is None:
        raise NumberingError(f"counter row for {series_key} vanished after it was created")
    return int(row[0])
