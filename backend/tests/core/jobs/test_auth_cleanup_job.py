"""
auth_cleanup runs from beat, not cron (BUILD_ORDER 7.1; closes TECH_DEBT DB-16).

The retention rules themselves are proven by users/tests/test_auth_cleanup.py against the command;
the job and the command share users.management.commands.auth_cleanup.purge_expired.
"""

import pytest
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from config.celery import app
from core.jobs import JobContext
from core.jobs.runner import execute
from core.jobs.schedules import sync_schedules
from core.registry import Cron, registry
from tests.factories import UserFactory
from users.models import LoginAttempt
from users.tests.test_auth_cleanup import ATTEMPTS, DAY, HOUR, attempt, exists, reset_token, session

pytestmark = pytest.mark.django_db

NAME = "users.auth_cleanup"


def run_once() -> int:
    return execute(registry.jobs.get(NAME), JobContext(run_id="test", job_name=NAME))


def test_it_is_a_registered_daily_job_on_a_consumed_queue():
    spec = registry.jobs.get(NAME)
    assert isinstance(spec.schedule, Cron)
    assert spec.schedule.fields()[2:] == ("*", "*", "*")  # every day
    assert spec.schedule.fields()[0] != "0"  # off the hour (§ 6 stagger)
    assert spec.enabled_by_default and not spec.destructive
    assert spec.queue == "bulk"
    assert app.tasks[NAME].acks_late  # idempotent, so late ack is allowed


def test_beat_has_an_enabled_entry_for_it():
    sync_schedules()
    row = PeriodicTask.objects.get(task=NAME)
    assert row.enabled and row.queue == "bulk"
    assert (row.crontab.minute, row.crontab.hour) == spec_minute_hour()


def spec_minute_hour():
    minute, hour, *_ = registry.jobs.get(NAME).schedule.fields()
    return minute, hour


def test_the_job_deletes_what_the_command_deletes_and_counts_it():
    user = UserFactory()
    now = timezone.now()
    old_attempt = attempt(ATTEMPTS * DAY + HOUR)
    fresh_attempt = attempt(HOUR)
    dead = session(user, expires_at=now - 31 * DAY)
    live = session(user, expires_at=now + DAY)
    used = reset_token(user, expires_at=now - 30 * DAY, used_at=now - 30 * DAY)
    assert run_once() == 3
    assert not any(exists(r) for r in (old_attempt, dead, used))
    assert all(exists(r) for r in (fresh_attempt, live))


def test_it_is_idempotent_a_second_run_finds_nothing():
    attempt(ATTEMPTS * DAY + HOUR)
    attempt(HOUR)
    assert run_once() == 1
    state = list(LoginAttempt.objects.order_by("pk").values_list("pk", flat=True))
    assert run_once() == 0
    assert list(LoginAttempt.objects.order_by("pk").values_list("pk", flat=True)) == state


def test_the_celery_task_runs_it():
    attempt(ATTEMPTS * DAY + HOUR)
    assert app.tasks[NAME].apply(task_id="beat-run").get() == 1
