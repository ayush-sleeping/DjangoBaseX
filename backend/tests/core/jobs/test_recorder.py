"""The run record (JOBS_AND_INTEGRATIONS.md § 7): from Celery's signals, never raising, on its own
connection, duration from perf_counter, error = type + scrubbed message."""

import logging

import pytest
from celery import Celery
from django.db import transaction

from config.celery import app
from core.jobs import enqueue, recorder
from core.jobs.celery import register_task
from core.registry import JobSpec
from tests.core.jobs.dbs import DATABASES, SEPARATE_CONNECTION, runs

pytestmark = pytest.mark.django_db(databases=DATABASES)


@pytest.fixture(autouse=True)
def _recorder_connected():
    # The recorder connects when the app finalizes, as in every real process (web via enqueue,
    # beat, worker).
    app.finalize(auto=True)


def local_task(func="tests.core.jobs.fakes.count_three", name="billing.count"):
    local = Celery("test", set_as_current=False)
    return register_task(
        local,
        JobSpec(
            name=name,
            func=func,
            owner_module="billing",
            description="A test job. If it stops, only these tests notice.",
        ),
    )


def test_a_successful_run_is_recorded_from_the_signals():
    assert local_task().apply(task_id="run-ok").get() == 3
    row = runs().get(task_id="run-ok")
    assert (row.job_name, row.status, row.count, row.trigger) == (
        "billing.count",
        "succeeded",
        3,
        "schedule",
    )
    assert row.started_at and row.finished_at and row.duration_ms is not None


def test_a_failed_run_records_type_and_scrubbed_message_never_a_traceback():
    local_task("tests.core.jobs.fakes.fails_with_a_secret").apply(task_id="run-bad")
    row = runs().get(task_id="run-bad")
    assert row.status == "failed"
    assert row.error_type == "ConnectionError"
    assert "hunter2" not in row.error_message and "s3cretpw" not in row.error_message
    assert "Traceback" not in row.error_message and "File " not in row.error_message
    assert len(row.error_message) <= recorder.MAX_ERROR_LENGTH


def test_a_long_error_is_truncated():
    _, message = recorder.error_text(ValueError("x" * 5000))
    assert len(message) == recorder.MAX_ERROR_LENGTH


def test_a_recorder_failure_never_fails_the_job(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("the monitor database is down")

    monkeypatch.setattr(recorder, "_upsert", broken)
    with caplog.at_level(logging.WARNING, logger="core.jobs.recorder"):
        assert local_task().apply(task_id="run-unrecorded").get() == 3
    assert not runs().filter(task_id="run-unrecorded").exists()
    assert any(r.getMessage() == "core.job.record_failed" for r in caplog.records)


def test_duration_comes_from_perf_counter_not_timestamps(monkeypatch):
    clock = iter([100.0, 100.013])
    monkeypatch.setattr(recorder.time, "perf_counter", lambda: next(clock))
    task = local_task()
    recorder.on_prerun(task_id="run-timed", task=task, kwargs={})
    recorder.on_postrun(sender=task, task_id="run-timed")
    assert runs().get(task_id="run-timed").duration_ms == 13


def test_a_publish_records_queued_with_its_trigger_and_queue(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        enqueue("users.auth_cleanup")  # a real publish over memory://, after the commit
    row = runs().get(job_name="users.auth_cleanup", status="queued")
    assert (row.queue, row.trigger) == ("bulk", "on_demand")
    assert row.queued_at is not None and row.started_at is None
    with app.connection_for_write() as conn:
        conn.default_channel.queue_purge("bulk")


def test_a_late_queued_record_never_overwrites_a_started_run():
    task = local_task()
    recorder.on_prerun(task_id="run-race", task=task, kwargs={})
    recorder.on_published(
        sender="billing.count",
        headers={"id": "run-race", "task": "billing.count"},
        body=((), {"trigger": "on_demand"}, {}),
        routing_key="default",
    )
    row = runs().get(task_id="run-race")
    assert (row.status, row.trigger) == ("started", "on_demand")
    assert row.queued_at is not None


@pytest.fixture
def publisher_wins_the_race(monkeypatch):
    """Deterministically lose the race update_or_create has. Our lookup ran before the publisher's
    INSERT landed (in another process, so outside our savepoint), and our own INSERT then hits the
    unique key."""
    from django.db.models.query import QuerySet

    from core.models import JobRun

    recorder.on_published(  # the publisher's row, already committed by the time we insert
        sender="billing.count",
        headers={"id": "run-lost", "task": "billing.count"},
        body=((), {"trigger": "on_demand"}, {}),
        routing_key="default",
    )
    real = QuerySet.update_or_create
    lost = []

    def lookup_missed(self, defaults=None, **kwargs):
        if self.model is not JobRun or lost:
            return real(self, defaults=defaults, **kwargs)
        lost.append(True)
        return self.create(**kwargs, **(defaults or {}))  # what a missed lookup does next

    monkeypatch.setattr(QuerySet, "update_or_create", lookup_missed)
    return lost


@pytest.mark.parametrize(
    ("write", "expected"),
    [
        (
            # the worker sees the kwargs the publisher sent, trigger included
            lambda task: recorder.on_prerun(
                task_id="run-lost", task=task, kwargs={"trigger": "on_demand"}
            ),
            "started",
        ),
        (
            lambda task: recorder.on_success(sender=_with_id(task, "run-lost"), result=3),
            "succeeded",
        ),
        (
            lambda task: recorder.on_failure(
                sender=task, task_id="run-lost", exception=ValueError("boom")
            ),
            "failed",
        ),
    ],
    ids=["started", "succeeded", "failed"],
)
def test_a_state_write_that_loses_the_insert_race_still_lands(
    publisher_wins_the_race, caplog, write, expected
):
    with caplog.at_level(logging.WARNING, logger="core.jobs.recorder"):
        write(local_task())
    assert publisher_wins_the_race == [True]  # the INSERT really did lose
    row = runs().get(task_id="run-lost")
    assert row.status == expected  # the worker's state wins over the publisher's "queued"
    assert row.queued_at is not None and row.trigger == "on_demand"  # the publisher's part kept
    assert not any(r.getMessage() == "core.job.record_failed" for r in caplog.records)


def _with_id(task, task_id):
    task.request.id = task_id
    return task


def test_an_unregistered_task_is_recorded_dead():
    recorder.on_unknown(name="billing.renamed_away", id="run-dead", exc=KeyError("no such task"))
    row = runs().get(task_id="run-dead")
    assert (row.job_name, row.status, row.error_type) == (
        "billing.renamed_away",
        "dead",
        "KeyError",
    )


def test_celerys_own_tasks_are_not_recorded():
    recorder.on_published(
        sender="celery.chord_unlock", headers={"id": "internal", "task": "celery.chord_unlock"}
    )
    assert not runs().filter(task_id="internal").exists()


def test_retry_attempts_are_recorded_as_retry():
    assert recorder._trigger({"trigger": "on_demand"}, retries=2) == "retry"


@pytest.mark.skipif(
    not SEPARATE_CONNECTION,
    reason="needs the recorder on its own connection: PostgreSQL only (config/settings_test)",
)
def test_a_rolled_back_job_still_records_its_failure():
    """
    The job writes, fails, and its transaction rolls back. The record of the failure, written on
    the monitor connection while that transaction was still open, survives the rollback.

    The task runs as a worker runs it: apply() with propagate off, so Celery handles the failure
    and sends task_failure. Not apply(throw=True): that re-raises before task_failure is sent (see
    test_eager_propagate_never_sends_task_failure), a path no worker takes.
    """
    from users.models import LoginAttempt

    class RollBack(Exception):
        pass

    with pytest.raises(RollBack), transaction.atomic():
        result = local_task("tests.core.jobs.fakes.writes_then_fails").apply(task_id="run-rb")
        assert result.failed()
        assert LoginAttempt.objects.filter(identifier="rolled-back@example.com").exists()
        raise RollBack  # the job's transaction ends in a rollback
    assert not LoginAttempt.objects.filter(identifier="rolled-back@example.com").exists()
    row = runs().get(task_id="run-rb")
    assert (row.status, row.error_type) == ("failed", "RuntimeError")


def test_eager_propagate_never_sends_task_failure():
    """Pins the Celery behaviour the test above depends on: with propagate on, the tracer
    re-raises in on_error before sending task_failure, so nothing records the failure. Workers
    never propagate, and eager mode is refused outside tests (dbx.jobs.E013)."""
    from celery import signals

    fired = []

    def receiver(**kwargs):
        fired.append(kwargs["task_id"])

    signals.task_failure.connect(receiver, weak=False)
    try:
        task = local_task("tests.core.jobs.fakes.fails_with_a_secret")
        with pytest.raises(ConnectionError):
            task.apply(task_id="eager-throw", throw=True)
        task.apply(task_id="eager-handled")
    finally:
        signals.task_failure.disconnect(receiver)
    assert fired == ["eager-handled"]
