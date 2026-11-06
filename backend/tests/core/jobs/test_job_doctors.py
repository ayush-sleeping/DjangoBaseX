"""The queue and schedule doctors, through `manage.py doctor` (JOBS_AND_INTEGRATIONS.md § 8;
BUILD_ORDER 7.2: doctor exits non-zero on a planted problem)."""

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from core.jobs import doctors as job_doctors
from core.models import JobSchedule
from core.registry import registry
from tests.core.jobs.dbs import DATABASES, runs

pytestmark = pytest.mark.django_db(databases=DATABASES)


def doctor(*keys) -> tuple[int, dict]:
    out = StringIO()
    try:
        call_command("doctor", "--json", "--only", ",".join(keys), stdout=out, stderr=StringIO())
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, {d["doctor"]: d for d in json.loads(out.getvalue())["doctors"]}


def codes(report: dict, key: str) -> set[str]:
    return {f["code"] for f in report[key]["findings"]}


def _run(**fields):
    defaults = {"task_id": f"t-{runs().count()}", "job_name": "users.auth_cleanup", "queue": "bulk"}
    return runs().create(**(defaults | fields))


# --- Clean ---------------------------------------------------------------------------------


def test_a_fresh_install_is_clean():
    code, report = doctor("queue", "schedule")
    assert code == 0, report
    assert codes(report, "schedule") == set()
    # memory:// cannot be peeked without consuming: an advisory, not a failure
    assert codes(report, "queue") == {"queue.not_inspected"}


# --- Planted problems: schedule --------------------------------------------------------------


def test_an_unowned_row_holding_a_jobs_name_fails():
    PeriodicTask.objects.filter(name="users.auth_cleanup").delete()  # cascades the ownership row
    every = IntervalSchedule.objects.create(every=60, period=IntervalSchedule.SECONDS)
    PeriodicTask.objects.create(name="users.auth_cleanup", task="x.y", interval=every)
    code, report = doctor("schedule")
    assert code == 1
    assert "schedule.conflict" in codes(report, "schedule")


def test_a_schedule_missing_from_beat_fails():
    PeriodicTask.objects.filter(name="users.auth_cleanup").delete()
    code, report = doctor("schedule")
    assert code == 1
    assert "schedule.not_synced" in codes(report, "schedule")


def test_an_overdue_scheduled_job_fails():
    _run(status="succeeded", started_at=timezone.now() - timedelta(days=3))
    code, report = doctor("schedule")
    assert code == 1
    assert "schedule.overdue" in codes(report, "schedule")


def test_a_failing_scheduled_job_fails():
    _run(status="failed", started_at=timezone.now() - timedelta(hours=1), error_type="OSError")
    code, report = doctor("schedule")
    assert code == 1 and "schedule.failing" in codes(report, "schedule")


def test_a_schedule_that_never_ran_past_its_grace_fails():
    JobSchedule.objects.filter(job_name="users.auth_cleanup").update(
        created_at=timezone.now() - timedelta(days=2)
    )
    code, report = doctor("schedule")
    assert code == 1 and "schedule.never_run" in codes(report, "schedule")


def test_a_new_schedule_that_has_not_run_yet_is_not_an_incident():
    assert doctor("schedule")[0] == 0


def test_an_unowned_beat_row_is_an_advisory():
    every = IntervalSchedule.objects.create(every=60, period=IntervalSchedule.SECONDS)
    PeriodicTask.objects.create(name="hand-made", task="users.auth_cleanup", interval=every)
    code, report = doctor("schedule")
    assert code == 0 and "schedule.unowned" in codes(report, "schedule")


# --- Planted problems: queue ---------------------------------------------------------------------


def test_a_stalled_queue_fails():
    _run(status="queued", queued_at=timezone.now() - timedelta(hours=1))
    code, report = doctor("queue")
    assert code == 1 and "queue.stalled" in codes(report, "queue")


def test_a_dead_task_fails():
    _run(job_name="billing.renamed_away", status="dead", finished_at=timezone.now())
    code, report = doctor("queue")
    assert code == 1 and "queue.dead_task" in codes(report, "queue")


@override_settings(CELERY_ACCEPT_CONTENT=["json", "pickle"])
def test_celery_config_comes_from_the_real_system_check():
    code, report = doctor("queue")
    assert code == 1 and "queue.config.dbx.jobs.E012" in codes(report, "queue")


def test_unregistered_task_names_waiting_in_redis_fail(monkeypatch):
    messages = {"bulk": [json.dumps({"headers": {"task": "billing.renamed_away"}}).encode()]}

    class FakeConnection:
        def __init__(self, url):
            self.default_channel = type("C", (), {"client": self})()
            self.default_channel.client = self

        def lrange(self, name, start, end):
            return messages.get(name, [])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import kombu

    monkeypatch.setattr(kombu, "Connection", FakeConnection)
    with override_settings(CELERY_BROKER_URL="redis://broker.internal:6379/1"):
        findings = job_doctors._peek_unregistered()
    assert [(f.code, f.subject) for f in findings] == [
        ("queue.unregistered_waiting", "bulk:billing.renamed_away")
    ]


# --- The health check -----------------------------------------------------------------------------


def test_the_jobs_health_check_is_registered_and_never_critical():
    check = next(c for c in registry.health.checks() if c.key == "jobs")
    assert check.critical is False
    assert check.check() is True  # a fresh install is green
