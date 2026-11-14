"""The twice-daily ops digest (7.8; § 16): one message, every row, all-clear, stamped on accept."""

import pytest
from django.core import mail

from core.models import Incident, OpsAlert, OpsDigestRun
from core.notifications import channels
from core.ops import AlertKind, Problem, alert, digest, incidents, quiet_hours
from tests.core.ops.conftest import utc

pytestmark = pytest.mark.django_db
NINE_FIVE = utc(2026, 11, 14, 9, 5)


def held(key):
    alert(key, source="queue", reason="slow", title=f"Slow {key}", kind=AlertKind.DEGRADED)


def test_empty_digest_says_all_clear(digest_route, flush, sent_mail):
    flush(lambda: digest.run_digest(NINE_FIVE))
    assert sent_mail() == ["Ops digest: all clear"]
    assert "All clear." in mail.outbox[0].body and "Next digest 17:00." in mail.outbox[0].body


def test_all_clear_names_the_last_sent_digest(digest_route, flush):
    flush(lambda: digest.run_digest(NINE_FIVE))
    flush(lambda: digest.settle(NINE_FIVE))
    flush(lambda: digest.run_digest(utc(2026, 11, 14, 17, 5)))
    assert "all clear since 09:00" in mail.outbox[-1].subject


def test_one_message_carries_every_held_alert_and_open_incident(route, digest_route, flush):
    for key in ("a", "b", "c"):
        flush(lambda k=key: held(k))
    flush(lambda: incidents.sync("db", {"k": Problem("Database slow")}, now=NINE_FIVE))
    flush(lambda: digest.run_digest(NINE_FIVE))
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "3 held alert(s), 1 open incident(s)" in mail.outbox[0].subject
    assert all(f"Slow {k}" in body for k in "abc") and "Database slow" in body


def test_held_alerts_are_released_only_after_the_provider_accepts(route, digest_route, flush):
    flush(lambda: held("a"))
    flush(lambda: digest.run_digest(NINE_FIVE))
    assert OpsAlert.objects.get(subject_key="a").released_at is None  # handed over, not yet settled
    flush(lambda: digest.settle(NINE_FIVE))
    row = OpsAlert.objects.get(subject_key="a")
    assert row.released_at is not None and row.released_via == "digest"
    assert OpsDigestRun.objects.get().status == "sent"


def test_failed_digest_contents_roll_into_the_next(route, digest_route, flush, monkeypatch):
    flush(lambda: held("a"))
    real = channels.EmailChannel.send
    monkeypatch.setattr(
        channels.EmailChannel, "send", lambda self, m: channels.DeliveryResult.rejected("down")
    )
    flush(lambda: digest.run_digest(NINE_FIVE))
    flush(lambda: digest.settle(NINE_FIVE))
    assert OpsDigestRun.objects.get().status == "failed"
    assert OpsAlert.objects.get(subject_key="a").released_at is None  # not lost
    monkeypatch.setattr(channels.EmailChannel, "send", real)
    flush(lambda: digest.run_digest(utc(2026, 11, 14, 17, 5)))
    assert len(mail.outbox) == 1 and "Slow a" in mail.outbox[0].body


def test_one_digest_per_slot(digest_route, flush, sent_mail):
    flush(lambda: digest.run_digest(NINE_FIVE))
    flush(lambda: digest.run_digest(utc(2026, 11, 14, 9, 20)))
    assert len(sent_mail()) == 1


def test_digest_times_follow_the_configured_timezone(db, setting):
    setting("operations.alerts.digest_times", ["09:00"])
    setting("operations.alerts.timezone", "Asia/Kolkata")  # 09:00 IST is 03:30 UTC
    assert quiet_hours.latest_slot(utc(2026, 11, 14, 3, 25)) == utc(2026, 11, 13, 3, 30)
    assert quiet_hours.latest_slot(utc(2026, 11, 14, 3, 35)) == utc(2026, 11, 14, 3, 30)
    assert quiet_hours.next_slot(utc(2026, 11, 14, 3, 35)) == utc(2026, 11, 15, 3, 30)


def test_a_digest_waits_out_quiet_hours(digest_route, flush, setting, sent_mail):
    setting("operations.alerts.quiet_start", "08:00")
    setting("operations.alerts.quiet_end", "10:00")
    flush(lambda: digest.run_digest(NINE_FIVE))
    assert sent_mail() == []
    flush(lambda: digest.run_digest(utc(2026, 11, 14, 10, 5)))
    assert len(sent_mail()) == 1


def test_a_digest_that_the_outbox_never_delivers_is_given_up_on(db):
    run = OpsDigestRun.objects.create(slot_at=NINE_FIVE)
    OpsDigestRun.objects.filter(pk=run.pk).update(created_at=utc(2026, 11, 14, 9, 5))
    assert digest.settle(utc(2026, 11, 14, 9, 30)) == 0  # not dispatched yet: wait
    assert digest.settle(utc(2026, 11, 14, 10, 30)) == 1
    assert OpsDigestRun.objects.get().status == "failed"
    assert not Incident.objects.exists()
