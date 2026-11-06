"""sync_schedules(): reconcile, never rebuild (JOBS_AND_INTEGRATIONS.md § 6)."""

from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django_celery_beat.models import IntervalSchedule, PeriodicTask, PeriodicTasks

from core.jobs.schedules import sync_schedules
from core.models import JobSchedule
from core.registry import Cron, Interval, JobRegistry, JobSpec

pytestmark = pytest.mark.django_db


def spec(name="billing.close_usage", **overrides) -> JobSpec:
    values = {
        "name": name,
        "func": "tests.core.jobs.fakes.count_three",
        "owner_module": "billing",
        "description": "Closes usage windows. If it stops, invoices are generated empty.",
        "schedule": Cron("20 0 * * *"),
    }
    return JobSpec(**(values | overrides))


def jobs(*specs) -> JobRegistry:
    registry = JobRegistry()
    for s in specs:
        registry.register(s)
    return registry


@pytest.fixture(autouse=True)
def _empty_schedule():
    # post_migrate synced the real registry; these tests start from no owned rows.
    PeriodicTask.objects.all().delete()


def test_a_scheduled_spec_gets_a_row_it_owns():
    report = sync_schedules(jobs=jobs(spec(queue="bulk"), spec("billing.manual", schedule=None)))
    assert report.created == ["billing.close_usage"]  # an unscheduled job gets no row
    row = PeriodicTask.objects.get()
    assert (row.name, row.task, row.queue, row.enabled) == (
        "billing.close_usage",
        "billing.close_usage",
        "bulk",
        True,
    )
    assert (row.crontab.minute, row.crontab.hour, str(row.crontab.timezone)) == ("20", "0", "UTC")
    assert row.expire_seconds == 86_400 * 9 // 10  # below the period
    assert JobSchedule.objects.get().periodic_task == row


def test_sync_twice_is_a_no_op():
    registry = jobs(spec(), spec("billing.sweep", schedule=Interval(900)))
    sync_schedules(jobs=registry)
    before = list(PeriodicTask.objects.order_by("name").values())
    report = sync_schedules(jobs=registry)
    assert not report.changed
    assert list(PeriodicTask.objects.order_by("name").values()) == before


def test_a_changed_spec_updates_its_row():
    sync_schedules(jobs=jobs(spec()))
    report = sync_schedules(jobs=jobs(spec(schedule=Cron("45 1 * * *"), queue="bulk")))
    assert report.updated == ["billing.close_usage"]
    row = PeriodicTask.objects.get()
    assert (row.crontab.minute, row.crontab.hour, row.queue) == ("45", "1", "bulk")


def test_a_removed_specs_row_is_deleted():
    sync_schedules(jobs=jobs(spec(), spec("billing.gone")))
    report = sync_schedules(jobs=jobs(spec()))
    assert report.deleted == ["billing.gone"]
    assert list(PeriodicTask.objects.values_list("name", flat=True)) == ["billing.close_usage"]
    assert list(JobSchedule.objects.values_list("job_name", flat=True)) == ["billing.close_usage"]


def test_a_foreign_row_survives():
    every_minute = IntervalSchedule.objects.create(every=60, period=IntervalSchedule.SECONDS)
    PeriodicTask.objects.create(name="hand-made", task="billing.close_usage", interval=every_minute)
    sync_schedules(jobs=jobs(spec("billing.other")))
    sync_schedules(jobs=jobs())
    assert list(PeriodicTask.objects.values_list("name", flat=True)) == ["hand-made"]


def test_an_operators_disable_survives_a_resync():
    sync_schedules(jobs=jobs(spec()))
    PeriodicTask.objects.filter(name="billing.close_usage").update(enabled=False)
    sync_schedules(jobs=jobs(spec(description="Reworded. If it stops, invoices are empty.")))
    assert PeriodicTask.objects.get().enabled is False


def test_a_job_off_by_default_is_created_disabled():
    sync_schedules(jobs=jobs(spec(destructive=True, enabled_by_default=False)))
    assert PeriodicTask.objects.get().enabled is False


def test_update_changed_is_called_after_bulk_edits():
    # django-celery-beat's own save signals also mark changes; the sync's explicit call is the one
    # that covers deletes and anything a future bulk update writes without a signal.
    with mock.patch.object(PeriodicTasks, "update_changed") as marker:
        sync_schedules(jobs=jobs(spec()))
        assert marker.called
        marker.reset_mock()
        sync_schedules(jobs=jobs(spec()))  # nothing changed: no marker
        assert not marker.called
        sync_schedules(jobs=jobs())  # a delete: marked
        assert marker.called


def test_dry_run_reports_and_writes_nothing():
    report = sync_schedules(dry_run=True, jobs=jobs(spec()))
    assert report.created == ["billing.close_usage"]
    assert not PeriodicTask.objects.exists()


def test_interval_jobs_are_staggered_deterministically():
    every_hour = Interval(3600)
    sync_schedules(
        jobs=jobs(spec("billing.a", schedule=every_hour), spec("billing.b", schedule=every_hour))
    )
    starts = {row.name: row.start_time for row in PeriodicTask.objects.all()}
    offsets = {name: (t.minute * 60 + t.second) for name, t in starts.items()}
    assert offsets["billing.a"] != offsets["billing.b"]


def test_the_command_prints_the_diff():
    out = StringIO()
    call_command("sync_schedules", "--dry-run", stdout=out)
    assert "would create users.auth_cleanup" in out.getvalue()
    out = StringIO()
    call_command("sync_schedules", stdout=out)
    call_command("sync_schedules", stdout=out)
    assert out.getvalue().splitlines() == [
        "created users.auth_cleanup",
        "schedules already match the registry",
    ]


def test_an_unowned_row_holding_a_jobs_name_is_a_conflict_not_a_crash(caplog):
    every_minute = IntervalSchedule.objects.create(every=60, period=IntervalSchedule.SECONDS)
    PeriodicTask.objects.create(
        name="billing.close_usage", task="something.else", interval=every_minute, enabled=False
    )
    before = list(PeriodicTask.objects.values())
    report = sync_schedules(jobs=jobs(spec(), spec("billing.other")))
    assert report.conflicts == ["billing.close_usage"]
    assert report.created == ["billing.other"]  # the rest of the sync still happens
    foreign = PeriodicTask.objects.get(name="billing.close_usage")
    assert [r for r in before if r["name"] == "billing.close_usage"] == [
        r for r in PeriodicTask.objects.values() if r["id"] == foreign.id
    ]  # untouched, not adopted
    assert not JobSchedule.objects.filter(job_name="billing.close_usage").exists()
    assert any(
        r.levelname == "ERROR" and r.getMessage() == "core.job.schedule_conflict"
        for r in caplog.records
    )


def test_the_post_migrate_hook_survives_a_conflict():
    from core.apps import _sync_schedules

    every_minute = IntervalSchedule.objects.create(every=60, period=IntervalSchedule.SECONDS)
    PeriodicTask.objects.create(name="users.auth_cleanup", task="x.y", interval=every_minute)
    _sync_schedules(sender=None)  # the real registry; must not raise inside migrate
    assert PeriodicTask.objects.get(name="users.auth_cleanup").task == "x.y"


def test_the_command_reports_a_conflict():
    every_minute = IntervalSchedule.objects.create(every=60, period=IntervalSchedule.SECONDS)
    PeriodicTask.objects.create(name="users.auth_cleanup", task="x.y", interval=every_minute)
    err = StringIO()
    call_command("sync_schedules", stdout=StringIO(), stderr=err)
    assert "conflict users.auth_cleanup" in err.getvalue()


def test_an_empty_registry_means_no_jobs_not_the_global_one():
    sync_schedules(jobs=jobs(spec()))
    report = sync_schedules(jobs=JobRegistry())
    assert report.deleted == ["billing.close_usage"]
    assert not PeriodicTask.objects.exists()
