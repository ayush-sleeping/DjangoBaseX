"""The business calendar (DOMAIN_PRIMITIVES.md § 4, BUILD_ORDER 9.4): platform-timezone working
days, holidays as data, ICS import with the standard library only."""

from datetime import UTC, date, datetime

import pytest
from django.core.management import call_command

from core import business_calendar as cal
from core.models import Holiday

pytestmark = pytest.mark.django_db


def holiday(*days):
    for d in days:
        Holiday.objects.create(date=d, name="H")


def test_weekends_are_not_business_days():
    assert cal.is_business_day(date(2026, 11, 13))  # Friday
    assert not cal.is_business_day(date(2026, 11, 14))  # Saturday


def test_add_business_days_skips_weekends_and_a_long_weekend():
    holiday(date(2026, 11, 16))  # the Monday
    assert cal.add_business_days(date(2026, 11, 13), 1) == date(2026, 11, 17)  # Fri + 1 -> Tue
    assert cal.add_business_days(date(2026, 11, 14), 1) == date(2026, 11, 17)  # Sat + 1 -> Tue
    assert cal.add_business_days(date(2026, 11, 17), -1) == date(2026, 11, 13)  # Tue - 1 -> Fri
    assert cal.add_business_days(date(2026, 11, 13), 5) == date(2026, 11, 23)


def test_zero_days_is_the_day_itself_and_next_business_day_rolls_forward():
    sat = date(2026, 11, 14)
    assert cal.add_business_days(sat, 0) == sat
    assert cal.next_business_day(sat, inclusive=True) == date(2026, 11, 16)
    assert cal.next_business_day(date(2026, 11, 13)) == date(2026, 11, 16)


def test_year_boundary_over_a_holiday_and_a_leap_day():
    holiday(date(2027, 1, 1))  # Friday
    assert cal.add_business_days(date(2026, 12, 31), 1) == date(2027, 1, 4)  # Thu + 1 -> Mon
    assert cal.add_business_days(date(2028, 2, 28), 1) == date(
        2028, 2, 29
    )  # a Tuesday: leap day works
    assert cal.add_business_days(date(2028, 2, 29), 1) == date(2028, 3, 1)


def test_business_days_between_counts_the_half_open_range():
    holiday(date(2026, 11, 16))
    assert cal.business_days_between(date(2026, 11, 13), date(2026, 11, 17)) == 1
    assert cal.business_days_between(date(2026, 11, 17), date(2026, 11, 13)) == -1


def test_the_local_date_follows_the_platform_timezone_not_utc(setting_override):
    instant = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)  # Friday 20:00 UTC
    setting_override("platform.timezone", "Asia/Kolkata")  # already Saturday 01:30 there
    assert cal.local_date(instant) == date(2026, 11, 14)
    assert not cal.is_business_day(cal.local_date(instant))
    setting_override("platform.timezone", "America/Los_Angeles")  # still Friday 12:00
    assert cal.local_date(instant) == date(2026, 11, 13)
    assert cal.is_business_day(cal.local_date(instant))


def test_dst_changes_do_not_move_the_calendar_day(setting_override):
    setting_override("platform.timezone", "America/New_York")
    spring = datetime(2026, 3, 8, 7, 30, tzinfo=UTC)  # 03:30 EDT, just after the 02:00 jump
    fall = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 01:30 EDT, the first of two 01:30s
    assert cal.local_date(spring) == date(2026, 3, 8)
    assert cal.local_date(fall) == date(2026, 11, 1)
    assert cal.local_date(datetime(2026, 11, 1, 6, 30, tzinfo=UTC)) == date(
        2026, 11, 1
    )  # repeat hour


def test_a_naive_datetime_is_refused():
    with pytest.raises(cal.CalendarError):
        cal.local_date(datetime(2026, 1, 1))


ICS = (
    "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261225\r\nSUMMARY:Christmas\\, Day\r\n"
    "END:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261231\r\nDTEND;VALUE=DATE:20270102\r\n"
    "SUMMARY:Year end\r\n shutdown\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART:20261110T090000Z\r\n"
    "SUMMARY:A meeting\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_ics_parsing_folds_lines_expands_ranges_and_ignores_timed_events():
    parsed = cal.parse_ics(ICS)
    assert parsed == [
        (date(2026, 12, 25), "Christmas, Day"),
        (date(2026, 12, 31), "Year endshutdown"),
        (date(2027, 1, 1), "Year endshutdown"),
    ]


def test_a_malformed_all_day_date_is_an_error_naming_the_value():
    bad = "BEGIN:VEVENT\nDTSTART;VALUE=DATE:2026-13-45\nEND:VEVENT\n"
    with pytest.raises(cal.CalendarError, match="2026-13-45"):
        cal.parse_ics(bad)


def test_importing_twice_adds_each_date_once_and_keeps_manual_rows(tmp_path):
    Holiday.objects.create(date=date(2026, 12, 25), name="Our name")
    assert cal.import_holidays(ICS) == {"created": 2, "skipped": 1}
    assert cal.import_holidays(ICS) == {"created": 0, "skipped": 3}
    assert Holiday.objects.get(date=date(2026, 12, 25)).name == "Our name"
    path = tmp_path / "h.ics"
    path.write_text(ICS)
    call_command("import_holidays", str(path))
    assert Holiday.objects.count() == 3
