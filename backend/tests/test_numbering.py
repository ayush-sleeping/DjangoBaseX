"""
BUILD_ORDER 9.4 done-when 1: two concurrent reservations on a fresh database mint different numbers.

The concurrency tests use REAL threads, each with its own connection, committing for real. They
cannot use django_db(transaction=True): its teardown TRUNCATEs every table, which the audit log's
PostgreSQL trigger refuses (TRAPS.md). They take the database through pytest-django's blocker
instead, use a unique series per test and delete their own counter rows afterwards (core_sequence
is not audited).

Where they run: PostgreSQL (CI's pytest job, TEST_DATABASE_URL) and a file-backed SQLite
(TEST_DATABASE_URL=sqlite:////abs/path/app.sqlite3; settings_test derives a test_ file beside it).
On in-memory SQLite, the default, the multi-thread tests skip: that engine shares one cache between
threads and refuses concurrent writers with "table is locked", which says nothing about the code.
test_the_race_ran_on_postgres fails the PostgreSQL job if they ever skip there.
"""

import threading
import time
from datetime import UTC, date, datetime

import pytest
from django.db import connection, connections, transaction
from django.test.utils import CaptureQueriesContext

from core import numbering
from core.models import Sequence
from core.registry import NumberingSeries, Registry, RegistryError

RACED: dict[str, bool] = {}


def _series(key: str, gapless: bool, pattern="{PREFIX}-{YYYY}{MM}-{seq:04}", reset="monthly"):
    return NumberingSeries(key, "Test series", pattern, reset, gapless, "INV")


@pytest.fixture
def mint(monkeypatch):
    """Register series on a private registry the numbering module reads, never the process one."""
    reg = Registry()
    monkeypatch.setattr(numbering, "registry", reg)
    return reg.numbering.register


@pytest.fixture
def real_db(django_db_setup, django_db_blocker):
    """The test database with no wrapping transaction: what two real requests see."""
    with django_db_blocker.unblock():
        yield
        Sequence.objects.filter(series__startswith="race.").delete()
        connections.close_all()


def _in_memory() -> bool:
    name = str(connection.settings_dict["NAME"])
    return connection.vendor == "sqlite" and (name == ":memory:" or "mode=memory" in name)


def on(year=2026, month=9, day=29):
    return date(year, month, day)


# --- Registration --------------------------------------------------------------------------------


def test_gapless_has_no_default():
    with pytest.raises(TypeError):
        NumberingSeries("a.b", "A", "{seq}", "never")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("pattern", "reset", "why"),
    [
        ("INV-{seq:04}", "monthly", "monthly reset needs"),
        ("{YYYY}-{seq}", "monthly", "monthly reset needs"),
        ("{YYYY}-{MM}", "monthly", "exactly one {seq}"),
        ("{seq}-{seq}", "never", "exactly one {seq}"),
        ("{YYYY}-{bogus}-{seq}", "yearly", "unknown {token}"),
        ("{PREFIX}-{seq}", "never", "declares no prefix"),
    ],
)
def test_a_pattern_that_would_collide_or_is_malformed_is_refused(pattern, reset, why):
    with pytest.raises(RegistryError, match=why):
        Registry().numbering.register(
            NumberingSeries("t.s", "S", pattern, reset, True, "" if "PREFIX" in pattern else "P")
        )


# --- Rendering, peek, periods ---------------------------------------------------------------------


@pytest.mark.django_db
def test_peek_writes_nothing_and_reserve_moves_the_counter(mint):
    mint(_series("t.invoice", True))
    with CaptureQueriesContext(connection) as queries:
        assert numbering.peek("t.invoice", on=on()) == "INV-202609-0001"
    assert [q["sql"].split()[0] for q in queries] == ["SELECT"]  # no write, no lock
    assert not Sequence.objects.exists()
    with transaction.atomic():
        assert numbering.reserve("t.invoice", on=on()) == "INV-202609-0001"
        assert numbering.reserve("t.invoice", on=on()) == "INV-202609-0002"
    assert numbering.peek("t.invoice", on=on()) == "INV-202609-0003"


@pytest.mark.django_db
def test_a_new_period_restarts_and_width_is_a_minimum(mint):
    mint(_series("t.invoice", True))
    with transaction.atomic():
        assert numbering.reserve("t.invoice", on=on(2026, 9, 30)) == "INV-202609-0001"
        assert numbering.reserve("t.invoice", on=on(2026, 10, 1)) == "INV-202610-0001"
    Sequence.objects.filter(series="t.invoice", period_key="2026-10").update(last_value=9999)
    with transaction.atomic():
        assert numbering.reserve("t.invoice", on=on(2026, 10, 2)) == "INV-202610-10000"


@pytest.mark.django_db
def test_the_period_is_the_issue_date_in_the_platform_timezone(mint, setting_override):
    mint(_series("t.invoice", True))
    setting_override("platform.timezone", "Asia/Kolkata")
    late_utc = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)  # 01:30 on 1 October in Kolkata
    assert numbering.peek("t.invoice", on=late_utc) == "INV-202610-0001"
    setting_override("platform.timezone", "UTC")
    assert numbering.peek("t.invoice", on=late_utc) == "INV-202609-0001"


@pytest.mark.django_db
def test_scopes_have_their_own_counters(mint):
    mint(_series("t.invoice", True))
    with transaction.atomic():
        assert numbering.reserve("t.invoice", scope="a", on=on()).endswith("0001")
        assert numbering.reserve("t.invoice", scope="b", on=on()).endswith("0001")
        assert numbering.reserve("t.invoice", scope="a", on=on()).endswith("0002")


@pytest.mark.django_db
def test_an_unknown_series_is_an_error_not_a_default(mint):
    with pytest.raises(numbering.UnknownSeries):
        numbering.peek("nope.series")


# --- Gapless vs gap-tolerant (single thread, real transactions) -----------------------------------


def test_a_gapless_reserve_outside_a_transaction_is_refused(mint, real_db):
    mint(_series("race.refuse", True))
    with pytest.raises(numbering.NumberingError, match="inside the caller's transaction"):
        numbering.reserve("race.refuse", on=on())
    assert not Sequence.objects.filter(series="race.refuse").exists()


def test_a_rollback_returns_a_gapless_number_and_burns_a_gapped_one(mint, real_db):
    mint(_series("race.gapless", True))
    mint(_series("race.gapped", False))

    class Boom(Exception):
        pass

    for key in ("race.gapless", "race.gapped"):
        with pytest.raises(Boom), transaction.atomic():
            assert numbering.reserve(key, on=on()).endswith("0001")
            raise Boom
    with transaction.atomic():
        assert numbering.reserve("race.gapless", on=on()).endswith("0001")  # returned
    with transaction.atomic():
        assert numbering.reserve("race.gapped", on=on()).endswith("0002")  # burned


# --- Done-when 1: concurrent reservations on a FRESH counter ------------------------------------


def _race(series_key: str, workers: int, hold: float) -> list[str]:
    """`workers` threads reserve at once on a series whose counter row does not exist yet."""
    assert not Sequence.objects.filter(series=series_key).exists(), "the race must start fresh"
    barrier = threading.Barrier(workers, timeout=20)
    minted: list[str] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def worker():
        try:
            barrier.wait()
            with transaction.atomic():
                number = numbering.reserve(series_key, on=on())
                time.sleep(hold)  # keep the transaction open: the others must queue behind it
            with guard:
                minted.append(number)
        except BaseException as exc:  # noqa: BLE001 - reported below, never swallowed
            with guard:
                errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, f"a reservation failed under contention: {errors!r}"
    assert len(minted) == workers
    return minted


@pytest.mark.parametrize("gapless", [True, False], ids=["gapless", "gapped"])
def test_two_concurrent_reservations_on_a_fresh_database_mint_different_numbers(
    mint, real_db, gapless
):
    if _in_memory():
        pytest.skip(
            "in-memory SQLite cannot host concurrent writers; run on PostgreSQL or a file DB"
        )
    key = f"race.fresh_{'gapless' if gapless else 'gapped'}"
    mint(_series(key, gapless))
    mint(_series(key + "_many", gapless))
    two = _race(key, workers=2, hold=0.1)
    assert len(set(two)) == 2
    assert sorted(two) == ["INV-202609-0001", "INV-202609-0002"]  # no hole, no duplicate

    many = _race(key + "_many", workers=8, hold=0.02)
    assert sorted(many) == [f"INV-202609-{n:04d}" for n in range(1, 9)]
    RACED["done"] = True


def test_the_race_ran_on_postgres_in_ci(request):
    """A concurrency test that silently skips everywhere proves nothing: on PostgreSQL it ran."""
    if connection.vendor != "postgresql":
        pytest.skip("only asserted against PostgreSQL (the CI pytest job)")
    if request.config.option.collectonly or not request.session.items:
        return
    ran_here = any("two_concurrent" in item.name for item in request.session.items)
    assert ran_here and RACED.get("done"), "the concurrency test did not run to completion"
