"""Quiet hours: hold in the window, in the configured timezone, release ONE summary (7.8; § 18)."""

import pytest

from core.models import OpsAlert
from core.ops import AlertKind, alert, digest, quiet_hours
from tests.core.ops.conftest import utc

pytestmark = pytest.mark.django_db


def window(setting, start="22:00", end="07:00", zone=""):
    setting("operations.alerts.quiet_start", start)
    setting("operations.alerts.quiet_end", end)
    setting("operations.alerts.timezone", zone)


def test_window_crossing_midnight(db, setting):
    window(setting)
    inside = [utc(2026, 11, 14, 22, 0), utc(2026, 11, 14, 23, 59), utc(2026, 11, 15, 6, 59)]
    outside = [utc(2026, 11, 14, 21, 59), utc(2026, 11, 15, 7, 0), utc(2026, 11, 14, 12, 0)]
    assert all(quiet_hours.in_quiet_hours(t) for t in inside)
    assert not any(quiet_hours.in_quiet_hours(t) for t in outside)


def test_a_daytime_window(db, setting):
    window(setting, "13:00", "14:00")
    assert quiet_hours.in_quiet_hours(utc(2026, 11, 14, 13, 30))
    assert not quiet_hours.in_quiet_hours(utc(2026, 11, 14, 14, 0))


def test_window_is_read_in_the_configured_timezone_not_utc(db, setting):
    window(setting, zone="Asia/Kolkata")  # 22:00-07:00 IST = 16:30-01:30 UTC
    assert quiet_hours.in_quiet_hours(
        utc(2026, 11, 14, 21, 30)
    )  # 03:00 IST (21:30 is not UTC-quiet)
    assert not quiet_hours.in_quiet_hours(utc(2026, 11, 15, 2, 0))  # 07:30 IST (02:00 is UTC-quiet)


def test_an_empty_alert_timezone_follows_the_platform_timezone(db, setting):
    window(setting)
    setting("platform.timezone", "Asia/Kolkata")
    assert quiet_hours.in_quiet_hours(utc(2026, 11, 14, 21, 30))
    assert not quiet_hours.in_quiet_hours(utc(2026, 11, 15, 2, 0))


def test_dst_transition(db, setting):
    # New York springs forward 2026-03-08: 02:00 EST becomes 03:00 EDT. Window 01:30-03:30 local.
    window(setting, "01:30", "03:30", "America/New_York")
    assert quiet_hours.in_quiet_hours(utc(2026, 3, 8, 6, 45))  # 01:45 EST
    assert quiet_hours.in_quiet_hours(utc(2026, 3, 8, 7, 15))  # 03:15 EDT (02:xx never existed)
    assert not quiet_hours.in_quiet_hours(utc(2026, 3, 8, 7, 45))  # 03:45 EDT


def test_empty_settings_disable_quiet_hours(db, setting):
    assert not quiet_hours.in_quiet_hours(utc(2026, 11, 14, 23, 0))
    setting("operations.alerts.quiet_start", "22:00")  # an end is still missing: off
    assert not quiet_hours.in_quiet_hours(utc(2026, 11, 14, 23, 0))


def test_alerts_inside_the_window_are_held_and_the_ledger_says_so(route, flush, setting, at):
    window(setting)
    at(utc(2026, 11, 14, 23, 0))
    flush(lambda: alert("a", source="s", reason="r", title="A", kind=AlertKind.INFRA_OUTAGE))
    row = OpsAlert.objects.get()
    assert (row.decision, row.decision_reason) == ("held", "quiet_hours")


def test_release_is_one_message(route, flush, setting, at, sent_mail):
    window(setting)
    at(utc(2026, 11, 14, 23, 0))
    for key in ("a", "b", "c"):
        flush(
            lambda k=key: alert(
                k, source="s", reason="r", title=f"Alert {k}", kind=AlertKind.INFRA_OUTAGE
            )
        )
    flush(
        lambda: alert(
            "b",
            source="s",
            reason="r",
            title="Recovered b",
            kind=AlertKind.INFRA_OUTAGE,
            event="recovered",
        )
    )
    assert sent_mail() == []  # nothing posts to operators inside the window
    assert flush(lambda: digest.release_quiet(utc(2026, 11, 14, 23, 30))) == 0  # still quiet
    assert flush(lambda: digest.release_quiet(utc(2026, 11, 15, 7, 5))) == 4
    assert len(sent_mail()) == 1
    assert sent_mail()[0].startswith("While it was quiet (22:00–07:00): 4 alert(s) held")
    assert not OpsAlert.objects.filter(decision="held", released_at__isnull=True).exists()
    flush(lambda: digest.release_quiet(utc(2026, 11, 15, 7, 20)))
    assert len(sent_mail()) == 1  # released rows are not announced again
