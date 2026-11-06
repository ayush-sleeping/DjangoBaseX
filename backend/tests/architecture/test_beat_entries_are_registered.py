"""
Every beat entry names a registered task, and every scheduled spec has a beat entry
(JOBS_AND_INTEGRATIONS.md § 5, § 6; BUILD_ORDER 7.1). A beat row naming an unknown task publishes
a message no worker can run; a scheduled spec with no row never runs at all.

Against the rows the real sync writes (post_migrate already ran it on the test database).
"""

import pytest
from django_celery_beat.models import PeriodicTask

from config.celery import app
from core.jobs.schedules import sync_schedules
from core.registry import registry

pytestmark = pytest.mark.django_db


def unregistered_entries() -> list[str]:
    return sorted(
        f"{row.name} → {row.task}"
        for row in PeriodicTask.objects.all()
        if row.task not in app.tasks or row.task not in registry.jobs
    )


def test_every_beat_entry_names_a_registered_task():
    sync_schedules()
    assert PeriodicTask.objects.exists(), "the schedule is empty: the sync wrote nothing"
    assert unregistered_entries() == []


def test_every_scheduled_spec_has_a_beat_entry():
    sync_schedules()
    scheduled = {spec.name for spec in registry.jobs.specs() if spec.schedule}
    assert scheduled, "no scheduled job is registered"
    assert scheduled <= set(PeriodicTask.objects.values_list("task", flat=True))


def test_the_check_catches_a_row_naming_an_unknown_task():
    sync_schedules()
    PeriodicTask.objects.create(
        name="hand-made", task="billing.no_such_job", interval=_any_interval()
    )
    assert unregistered_entries() == ["hand-made → billing.no_such_job"]


def _any_interval():
    from django_celery_beat.models import IntervalSchedule

    return IntervalSchedule.objects.get_or_create(every=60, period=IntervalSchedule.SECONDS)[0]
