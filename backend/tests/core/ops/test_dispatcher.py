"""The dispatcher, its ledger and the instant/digest policy (7.8; § 14, § 15)."""

import logging

import pytest
from django.core.cache import cache

from core.models import Finding, OpsAlert
from core.notifications import channels
from core.ops import AlertKind, alert, dispatcher, policy

pytestmark = pytest.mark.django_db


def raise_alert(key="queue:billing:stalled", kind=AlertKind.INFRA_OUTAGE, **kwargs):
    return alert(key, source="queue", reason="stalled", title=f"Alert {key}", kind=kind, **kwargs)


def test_every_call_writes_a_ledger_row(route, flush, setting):
    flush(lambda: raise_alert("a"))  # instant
    flush(lambda: raise_alert("b", kind=AlertKind.DEGRADED))  # waits for the digest
    setting("operations.alerts.enabled", False)
    flush(lambda: raise_alert("c"))
    rows = {r.subject_key: (r.decision, r.decision_reason) for r in OpsAlert.objects.all()}
    assert rows == {
        "a": ("sent", ""),
        "b": ("held", "digest"),
        "c": ("skipped", "disabled"),
    }


def test_cooldown_survives_cache_clear(route, flush, sent_mail):
    flush(lambda: raise_alert())
    cache.clear()  # a deploy, a restart, a flushed Redis: the ledger must not forget
    flush(lambda: raise_alert())
    second = OpsAlert.objects.order_by("id").last()
    assert (second.decision, second.decision_reason) == ("skipped", "cooldown")
    assert len(sent_mail()) == 1


def test_cooldown_ends_with_its_window(route, flush, sent_mail):
    flush(lambda: raise_alert())
    from datetime import timedelta

    from django.utils import timezone

    OpsAlert.objects.update(created_at=timezone.now() - timedelta(minutes=31))
    flush(lambda: raise_alert())  # infra_outage cooldown is 30 minutes
    assert len(sent_mail()) == 2


def test_a_recovery_is_never_cooled_down(route, flush, sent_mail):
    flush(lambda: raise_alert())
    flush(lambda: raise_alert(event="recovered"))
    assert len(sent_mail()) == 2


def test_no_destination_is_reported_not_dropped(db, flush, caplog):
    with caplog.at_level(logging.ERROR, logger="core.ops"):
        flush(lambda: raise_alert())
    row = OpsAlert.objects.get()
    assert (row.decision, row.decision_reason) == ("skipped", "no_destination")
    assert any(r.message == "core.ops.no_destination" for r in caplog.records)
    assert Finding.objects.open().filter(kind="ops.no_destination").exists()


def test_a_route_clears_the_no_destination_finding(db, flush):
    flush(lambda: raise_alert("one"))
    from core.notifications import service

    service.save_route(
        actor=None,
        purpose_code="core.ops_alert",
        channel="email",
        target={"addresses": ["ops@example.com"]},
    )
    flush(lambda: raise_alert("two"))
    assert not Finding.objects.open().filter(kind="ops.no_destination").exists()


def test_storm_cap_holds_the_excess(route, flush, setting, sent_mail):
    setting("operations.alerts.max_instant_per_hour", 2)
    for key in ("a", "b", "c", "d"):
        flush(lambda key=key: raise_alert(key))
    decisions = [(r.subject_key, r.decision, r.decision_reason) for r in OpsAlert.objects.all()]
    assert ("c", "held", "storm_cap") in decisions and ("d", "held", "storm_cap") in decisions
    storm = [s for s in sent_mail() if s.startswith("Alert storm")]
    assert len(storm) == 1  # one message for the whole storm, not one per held alert
    assert len(sent_mail()) == 3


def test_a_dispatcher_failure_is_loud_and_never_raises(route, flush, monkeypatch, caplog):
    def explode(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(dispatcher, "notify", explode)
    with caplog.at_level(logging.ERROR, logger="core.ops"):
        outcome = flush(lambda: raise_alert())
    assert (outcome.decision, outcome.reason) == ("skipped", "dispatch_error")
    row = OpsAlert.objects.get()
    assert (row.decision, row.decision_reason) == ("skipped", "dispatch_error")
    assert any(r.message == "core.ops.dispatch_failed" for r in caplog.records)


def test_the_provider_answer_is_in_the_delivery_log_not_the_ledger(route, flush, monkeypatch):
    monkeypatch.setattr(
        channels.EmailChannel, "send", lambda self, m: channels.DeliveryResult.rejected("bad")
    )
    flush(lambda: raise_alert())
    assert OpsAlert.objects.get().decision == "sent"  # handed to notify(); see NotificationDelivery


# --- policy.decide: one test per allow-list row (§ 15) ------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        AlertKind.REGRESSION,
        AlertKind.INFRA_OUTAGE,
        AlertKind.MISCONFIGURATION,
        AlertKind.DEPLOY_BREAKAGE,
        AlertKind.FIRST_SIGHTING,
    ],
)
def test_an_allow_listed_kind_is_instant(route, kind):
    assert policy.decide(kind, "k").decision == "sent"


def test_cooldowns_are_per_kind_settings(route, setting):
    for kind, minutes in (("regression", 360), ("infra_outage", 30), ("misconfiguration", 360)):
        assert policy.cooldown_minutes(kind, policy.quiet_hours.policy()) == minutes


def test_unknown_kind_is_held(route):
    assert policy.decide("something_new", "k") == policy.Outcome("held", "digest")
    assert policy.decide(AlertKind.DEGRADED, "k") == policy.Outcome("held", "digest")


def test_a_held_problem_is_not_held_twice(route, flush):
    flush(lambda: raise_alert("slow", kind=AlertKind.DEGRADED))
    flush(lambda: raise_alert("slow", kind=AlertKind.DEGRADED))
    assert list(OpsAlert.objects.order_by("id").values_list("decision_reason", flat=True)) == [
        "digest",
        "already_held",
    ]
