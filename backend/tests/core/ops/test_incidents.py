"""Incidents: announced once, recovered once, nothing in between (7.8; § 17)."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction

from core.models import Incident, OpsAlert
from core.ops import AlertKind, Problem, incidents
from tests.core.ops.conftest import utc

pytestmark = pytest.mark.django_db
DOWN = {"db:unreachable": Problem("Database unreachable", AlertKind.INFRA_OUTAGE)}


def test_a_flapping_check_produces_one_incident_message_and_one_recovery_message(
    route, flush, sent_mail
):
    t = utc(2026, 11, 14, 10, 0)
    for minute, problems in enumerate([DOWN, {}, DOWN, {}, DOWN, {}]):
        flush(lambda p=problems, m=minute: incidents.sync("db", p, now=t + timedelta(minutes=m)))
    assert sent_mail() == ["Incident: Database unreachable", "Recovered: Database unreachable"]
    assert Incident.objects.filter(status="recovered").count() == 3  # the flaps are still history


def test_persisting_problem_announces_once(route, flush, sent_mail):
    t = utc(2026, 11, 14, 10, 0)
    for minute in range(6):
        flush(lambda m=minute: incidents.sync("db", DOWN, now=t + timedelta(minutes=m)))
    assert sent_mail() == ["Incident: Database unreachable"]
    assert Incident.objects.get().status == "open"


def test_flap_inside_confirm_window_is_silent(route, flush, sent_mail):
    t = utc(2026, 11, 14, 10, 0)
    flush(lambda: incidents.sync("queue", DOWN, confirm_after_minutes=10, now=t))
    flush(
        lambda: incidents.sync("queue", {}, confirm_after_minutes=10, now=t + timedelta(minutes=3))
    )
    assert sent_mail() == [] and not OpsAlert.objects.exists()
    assert Incident.objects.get().status == "recovered"


def test_a_problem_that_persists_past_the_window_is_announced(route, flush, sent_mail):
    t = utc(2026, 11, 14, 10, 0)
    flush(lambda: incidents.sync("queue", DOWN, confirm_after_minutes=10, now=t))
    assert sent_mail() == []
    flush(
        lambda: incidents.sync(
            "queue", DOWN, confirm_after_minutes=10, now=t + timedelta(minutes=11)
        )
    )
    assert sent_mail() == ["Incident: Database unreachable"]


def test_recovery_announced_once(route, flush, sent_mail):
    t = utc(2026, 11, 14, 10, 0)
    flush(lambda: incidents.sync("db", DOWN, now=t))
    for minute in (1, 2, 3):
        flush(lambda m=minute: incidents.sync("db", {}, now=t + timedelta(minutes=m)))
    assert sent_mail().count("Recovered: Database unreachable") == 1


def test_unannounced_incident_recovers_silently(db, flush, sent_mail, setting):
    setting("operations.alerts.enabled", False)  # the opening is skipped, so never announced
    t = utc(2026, 11, 14, 10, 0)
    flush(lambda: incidents.sync("db", DOWN, now=t))
    flush(lambda: incidents.sync("db", {}, now=t + timedelta(minutes=1)))
    assert sent_mail() == []
    assert not OpsAlert.objects.filter(event="recovered").exists()  # no lonely "recovered"


def test_one_open_incident_per_key(db):
    now = utc(2026, 11, 14, 10, 0)
    fields = {"source": "db", "key": "k", "label": "L", "kind": "degraded"}
    Incident.objects.create(first_seen_at=now, last_seen_at=now, **fields)
    with pytest.raises(IntegrityError), transaction.atomic():
        Incident.objects.create(first_seen_at=now, last_seen_at=now, **fields)
    Incident.objects.update(status="recovered", recovered_at=now)
    Incident.objects.create(first_seen_at=now, last_seen_at=now, **fields)  # history may repeat


def test_a_digest_kind_incident_is_held_for_the_digest_and_recovers_into_it(
    route, flush, sent_mail
):
    t = utc(2026, 11, 14, 10, 0)
    slow = {"q": Problem("Queue slow")}  # degraded: not on the allow-list
    flush(lambda: incidents.sync("queue", slow, now=t))
    flush(lambda: incidents.sync("queue", {}, now=t + timedelta(minutes=1)))
    assert sent_mail() == []
    assert list(OpsAlert.objects.order_by("id").values_list("event", "decision")) == [
        ("problem", "held"),
        ("recovered", "held"),
    ]
