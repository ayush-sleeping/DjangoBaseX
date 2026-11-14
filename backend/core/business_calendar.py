"""
The business calendar (DOMAIN_PRIMITIVES.md § 4, day-level). Working days are Monday to Friday
minus the rows of core_holiday; every question is answered in the PLATFORM timezone (the
`timezone` of the locale policy), never the server's and never UTC. Holidays are data (entered or
imported from ICS); no list ships in code.

A date here is a calendar date in the platform timezone. To ask about an instant, convert it with
local_date(), which is what a document issued at 23:30 local on the 31st needs.

Not built here (TECH_DEBT): intra-day business hours, per-tenant calendars, overrides.
"""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

WORKING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})  # Monday=0 (date.weekday())
_SEARCH_LIMIT_DAYS = 3660  # ten years without a working day means the calendar is unusable


class CalendarError(Exception):
    code = "calendar_error"


def platform_timezone() -> str:
    from core.formatting import LocalePolicy
    from core.settings_service import resolve

    return resolve(LocalePolicy).timezone


def local_date(at: datetime | None = None) -> date:
    """The calendar date of an instant (default: now) in the platform timezone."""
    at = at or timezone.now()
    if timezone.is_naive(at):
        raise CalendarError("local_date() needs an aware datetime; a naive one has no zone")
    return at.astimezone(ZoneInfo(platform_timezone())).date()


def _holidays_between(start: date, end: date) -> frozenset[date]:
    from core.models import Holiday

    low, high = min(start, end), max(start, end)
    return frozenset(
        Holiday.objects.filter(date__gte=low, date__lte=high).values_list("date", flat=True)
    )


def is_business_day(day: date) -> bool:
    from core.models import Holiday

    return day.weekday() in WORKING_WEEKDAYS and not Holiday.objects.filter(date=day).exists()


def next_business_day(day: date, *, inclusive: bool = False) -> date:
    """The first working day after `day` (or `day` itself when inclusive and it works)."""
    return add_business_days(day, 0 if inclusive else 1, _roll_forward=inclusive)


def add_business_days(day: date, n: int, *, _roll_forward: bool = False) -> date:
    """
    `n` working days after `day` (before, for a negative n). From a non-working day the count
    starts at the next working day: Saturday + 1 is Monday (or Tuesday over a Monday holiday),
    never Sunday. n == 0 returns `day` itself, which may not be a working day; use
    next_business_day(day, inclusive=True) to roll it forward.
    """
    step = 1 if n >= 0 or _roll_forward else -1
    remaining = abs(n)
    holidays = _holidays_between(
        day - timedelta(days=_SEARCH_LIMIT_DAYS if step < 0 else 0),
        day + timedelta(days=_SEARCH_LIMIT_DAYS if step > 0 else 0),
    )
    cursor = day

    def works(d: date) -> bool:
        return d.weekday() in WORKING_WEEKDAYS and d not in holidays

    if remaining == 0:
        if _roll_forward:
            while not works(cursor):
                cursor += timedelta(days=1)
        return cursor
    for _ in range(_SEARCH_LIMIT_DAYS):
        cursor += timedelta(days=step)
        if works(cursor):
            remaining -= 1
            if remaining == 0:
                return cursor
    raise CalendarError("no working day within ten years: is every weekday a holiday?")


def business_days_between(start: date, end: date) -> int:
    """Working days in (start, end]: Friday to the next Monday is 1."""
    if end < start:
        return -business_days_between(end, start)
    holidays = _holidays_between(start, end)
    count, cursor = 0, start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() in WORKING_WEEKDAYS and cursor not in holidays:
            count += 1
    return count


# --- ICS import (the minimal subset: all-day VEVENTs; standard library only) ----------------------

_DATE_VALUE = re.compile(r"^(\d{4})(\d{2})(\d{2})")


def parse_ics(text: str) -> list[tuple[date, str]]:
    """
    (date, name) for every VEVENT with an all-day DTSTART. A multi-day DTSTART..DTEND (exclusive)
    yields each day. Folded lines are unfolded. A timed event is not a holiday and is ignored;
    a malformed all-day DTSTART raises CalendarError naming the line.
    """
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    found: list[tuple[date, str]] = []
    event: dict[str, str] | None = None
    for line in lines:
        upper = line.strip().upper()
        if upper == "BEGIN:VEVENT":
            event = {}
        elif upper == "END:VEVENT" and event is not None:
            found.extend(_event_days(event))
            event = None
        elif event is not None and ":" in line:
            name, _, value = line.partition(":")
            event[name.split(";")[0].upper()] = value.strip()
            if name.upper().startswith("DTSTART") and "VALUE=DATE" in name.upper():
                event["_ALLDAY"] = "1"
            if name.upper().startswith("DTEND") and "VALUE=DATE" in name.upper():
                event["_ENDALLDAY"] = "1"
    return sorted(set(found))


def _ics_date(value: str) -> date:
    match = _DATE_VALUE.match(value)
    if not match:
        raise CalendarError(f"not an ICS date: {value!r}")
    try:
        return date(*(int(g) for g in match.groups()))
    except ValueError as exc:
        raise CalendarError(f"not an ICS date: {value!r}") from exc


def _event_days(event: dict[str, str]) -> list[tuple[date, str]]:
    start_raw = event.get("DTSTART")
    if not start_raw or not event.get("_ALLDAY"):
        return []  # a timed event is a meeting, not a holiday
    name = (event.get("SUMMARY") or "Holiday").replace("\\,", ",").replace("\\;", ";")[:128]
    start = _ics_date(start_raw)
    end = _ics_date(event["DTEND"]) if event.get("DTEND") and event.get("_ENDALLDAY") else None
    days = (
        [start]
        if end is None or end <= start
        else [start + timedelta(days=i) for i in range((end - start).days)]
    )
    return [(d, name) for d in days]


def import_holidays(text: str) -> dict[str, int]:
    """Idempotent: an existing date keeps its row (and its name); only new dates are added."""
    from core.models import Holiday

    created = skipped = 0
    for day, name in parse_ics(text):
        _, was_created = Holiday.objects.get_or_create(
            date=day, defaults={"name": name, "source": Holiday.Source.ICS}
        )
        created += was_created
        skipped += not was_created
    return {"created": created, "skipped": skipped}
