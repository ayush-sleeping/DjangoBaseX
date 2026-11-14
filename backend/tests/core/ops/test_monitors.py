"""Scheduled monitors report through the dispatcher and return normally (7.8; § 19)."""

import pytest

from core.models import Incident, OpsAlert
from core.ops import jobs, monitors
from core.registry import FAILURE, Doctor, Finding

pytestmark = pytest.mark.django_db


def doctor(key, findings=None, boom=False):
    def fn():
        if boom:
            raise RuntimeError("cannot check")
        return findings or []

    return Doctor(key=key, fn=fn, owner="tests", description="test doctor")


STALLED = Finding(FAILURE, "queue.stalled", "billing", "12 waiting", remedy="start a worker")


def test_findings_are_reported_through_the_dispatcher_and_the_run_returns_normally(
    route, flush, sent_mail
):
    count = flush(lambda: monitors.run([doctor("queue", [STALLED])]))
    assert count == 1  # a monitor that finds a problem has worked: no raise, no non-zero exit
    incident = Incident.objects.get()
    assert (incident.source, incident.kind, incident.status) == ("queue", "infra_outage", "pending")


def test_a_queue_problem_waits_for_its_confirm_window(route, flush, sent_mail):
    flush(lambda: monitors.run([doctor("queue", [STALLED])]))
    assert sent_mail() == []  # operations.incidents.queue_confirm_after_minutes is 10


def test_a_non_queue_problem_is_announced_at_once(route, flush, sent_mail):
    flush(lambda: monitors.run([doctor("dataplane", [STALLED])]))
    assert len(sent_mail()) == 1


def test_a_crashed_doctor_is_its_own_alert_and_recovers_nothing(route, flush, sent_mail):
    flush(lambda: monitors.run([doctor("dataplane", [STALLED])]))
    flush(lambda: monitors.run([doctor("dataplane", boom=True)]))
    assert Incident.objects.get().status == "open"  # not recovered by a check that never ran
    assert OpsAlert.objects.filter(subject_key="monitor:dataplane:crashed").exists()
    assert "Monitor could not check: dataplane" in sent_mail()


def test_doctor_housekeeping_findings_are_not_alerts(route, flush):
    ledger = Finding(FAILURE, "doctor.ledger_entry_fixed", "x", "remove it from the ledger")
    flush(lambda: monitors.run([doctor("dataplane", [ledger])]))
    assert not Incident.objects.exists()


def test_the_registered_job_runs_the_real_doctors_and_returns_an_int(route, flush):
    from core.jobs import JobContext

    result = flush(lambda: jobs.run_monitor(JobContext(run_id="t", job_name="ops.monitor")))
    assert isinstance(result, int)
