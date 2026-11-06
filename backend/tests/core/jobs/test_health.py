"""Job health and the monitor (JOBS_AND_INTEGRATIONS.md § 8): the states in precedence order,
worker_seen_recently, queue liveness, and the acceptance case: a stopped worker turns the monitor
red within three intervals while the failed-jobs count stays zero."""

from datetime import UTC, datetime, timedelta

import pytest
from django_celery_beat.models import PeriodicTask

from core.jobs import health
from core.jobs.schedules import sync_schedules
from core.registry import Cron, Interval, JobRegistry, JobSpec
from tests.core.jobs.dbs import DATABASES, runs

pytestmark = pytest.mark.django_db(databases=DATABASES)

T0 = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)  # a Monday
EVERY_MINUTE = Interval(60)


def spec(name="billing.sweep", schedule=EVERY_MINUTE, **overrides) -> JobSpec:
    values = {
        "name": name,
        "func": "tests.core.jobs.fakes.count_three",
        "owner_module": "billing",
        "description": "Sweeps. If it stops, nothing is swept.",
        "schedule": schedule,
    }
    return JobSpec(**(values | overrides))


def jobs(*specs) -> JobRegistry:
    registry = JobRegistry()
    for s in specs:
        registry.register(s)
    return registry


_ids = iter(range(10**6))


def run(name="billing.sweep", status="succeeded", started=None, queued=None, queue="default", **kw):
    return runs().create(
        task_id=f"t{next(_ids)}",
        job_name=name,
        status=status,
        queue=queue,
        queued_at=queued or started,
        started_at=started,
        finished_at=started + timedelta(seconds=1) if started and status != "started" else None,
        **kw,
    )


def state(s: JobSpec, now=T0, enabled=True) -> str:
    return health.job_health(s, now, enabled=enabled, policy=health.QueuePolicy()).state


# --- The states -----------------------------------------------------------------------------------


def test_ok():
    run(started=T0 - timedelta(seconds=30))
    assert state(spec()) == health.OK


def test_never_run_is_not_failing():
    assert state(spec()) == health.NEVER_RUN


def test_failing_is_the_last_terminal_run():
    run(started=T0 - timedelta(seconds=90))
    run(status="failed", started=T0 - timedelta(seconds=30), error_type="ValueError")
    assert state(spec()) == health.FAILING


def test_a_later_success_clears_failing():
    run(status="failed", started=T0 - timedelta(seconds=90))
    run(started=T0 - timedelta(seconds=30))
    assert state(spec()) == health.OK


def test_overdue_after_three_intervals_and_not_before():
    run(started=T0 - timedelta(seconds=180))
    assert state(spec()) == health.OK
    run(started=T0 - timedelta(seconds=181), name="billing.other")
    assert state(spec(), now=T0 + timedelta(seconds=1)) == health.OVERDUE


def test_disabled():
    assert state(spec(), enabled=False) == health.DISABLED


def test_disabled_beats_failing():
    run(status="failed", started=T0 - timedelta(seconds=30))
    assert state(spec(), enabled=False) == health.DISABLED


def test_never_run_beats_overdue():
    # Queued long ago and never started: that is "never ran", not "overdue".
    run(status="queued", started=None, queued=T0 - timedelta(hours=1))
    assert state(spec()) == health.NEVER_RUN


def test_failing_beats_overdue():
    run(status="failed", started=T0 - timedelta(hours=1))
    assert state(spec()) == health.FAILING


def test_a_dead_task_counts_as_failing():
    run(status="dead", started=T0 - timedelta(seconds=30))
    assert state(spec()) == health.FAILING


def test_an_on_demand_job_is_never_overdue():
    run(name="billing.export", started=T0 - timedelta(days=30))
    assert state(spec("billing.export", schedule=None)) == health.OK


def test_a_cron_job_is_overdue_once_its_fire_passes_unstarted():
    daily = spec("billing.close", schedule=Cron("20 0 * * *"))
    run(name="billing.close", started=datetime(2026, 3, 1, 0, 20, tzinfo=UTC))
    assert state(daily, now=datetime(2026, 3, 2, 0, 30, tzinfo=UTC)) == health.OK  # within grace
    assert state(daily, now=datetime(2026, 3, 2, 0, 36, tzinfo=UTC)) == health.OVERDUE


def test_the_owned_beat_rows_switch_is_the_enabled_state():
    registry = jobs(spec())
    sync_schedules(jobs=registry)
    run(started=T0 - timedelta(seconds=30))
    assert health.report(T0, jobs=registry).jobs[0].state == health.OK
    PeriodicTask.objects.filter(name="billing.sweep").update(enabled=False)
    assert health.report(T0, jobs=registry).jobs[0].state == health.DISABLED


# --- Queues and the worker --------------------------------------------------------------------


def test_empty_queue_is_alive():
    q = health.queue_health("default", T0, health.QueuePolicy())
    assert (q.alive, q.stalled, q.backlog) == (True, False, 0)


def test_a_backlog_with_a_recent_start_is_alive():
    run(started=T0 - timedelta(minutes=1))
    run(status="queued", queued=T0 - timedelta(minutes=2))
    assert health.queue_health("default", T0, health.QueuePolicy()).alive


def test_a_backlog_older_than_the_threshold_is_stalled():
    run(status="queued", queued=T0 - timedelta(minutes=16))
    q = health.queue_health("default", T0, health.QueuePolicy())
    assert q.stalled and not q.alive and q.backlog == 1


def test_quiet_but_dead_worker_is_not_ok():
    """Nothing failed and nothing is queued, but the every-minute job has not started for an
    hour: that is a dead worker, not a quiet one."""
    registry = jobs(spec())
    run(started=T0 - timedelta(hours=1))
    report = health.report(T0, jobs=registry)
    assert report.status == health.RED
    assert report.failed_runs == 0
    assert report.worker_seen_recently is False


def test_quiet_and_healthy_is_green():
    registry = jobs(spec())
    run(started=T0 - timedelta(seconds=20))
    report = health.report(T0, jobs=registry)
    assert (report.status, report.worker_seen_recently) == (health.GREEN, True)


def test_never_run_alone_is_not_red():
    # A new deploy is not an incident (§ 8); the schedule doctor escalates it after a grace.
    assert health.report(T0, jobs=jobs(spec())).status == health.GREEN


# --- Acceptance (BUILD_ORDER 7.2) -------------------------------------------------------------


def test_a_stopped_worker_turns_the_monitor_red_within_three_intervals_with_zero_failures():
    registry = jobs(spec())
    # The worker ran the every-minute job at T0, then stopped. Beat keeps publishing every
    # minute: queued runs pile up, none starts, none fails.
    run(started=T0)
    for minute in (1, 2, 3):
        run(status="queued", queued=T0 + timedelta(minutes=minute))

    at_two_intervals = health.report(T0 + timedelta(seconds=120), jobs=registry)
    assert at_two_intervals.status == health.GREEN  # not yet: no flapping on one slow run

    at_three_intervals = health.report(T0 + timedelta(seconds=181), jobs=registry)
    assert at_three_intervals.status == health.RED
    assert at_three_intervals.jobs[0].state == health.OVERDUE
    assert at_three_intervals.failed_runs == 0  # the failure view would have looked healthy
    assert any("billing.sweep is overdue" in r for r in at_three_intervals.reasons)

    later = health.report(T0 + timedelta(minutes=20), jobs=registry)
    assert later.worker_seen_recently is False
    assert any(q.name == "default" and q.stalled for q in later.queues)
