"""
Schedules are code, synced into the scheduler (JOBS_AND_INTEGRATIONS.md § 6).

sync_schedules() reconciles django-celery-beat's PeriodicTask rows with the job registry: it creates
the missing rows, updates the changed ones, deletes the registry-owned rows whose spec is gone, and
never touches a row the registry does not own (core_job_schedule records ownership). It runs on
every post_migrate and from `manage.py sync_schedules`.

`enabled` is written only when a row is created (from enabled_by_default) and never overwritten,
so an operator's toggle survives every later sync. Per-job settings overrides
(`jobs.<name>.enabled`) are not built yet.
"""

import json
import logging
import zlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.registry import Cron, Interval, JobSpec, registry

logger = logging.getLogger("core.jobs")

# --- Periods: deterministic, never relative to "now" --------------------------------------------

_CRON_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
CRON_FLOOR_SECONDS = 60  # one minute: no crontab fires more often


def _expand(text: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        base, _, step = part.partition("/")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start, end = (int(v) for v in base.split("-", 1))
        else:
            start = int(base)
            end = high if step else start
        values.update(range(start, end + 1, int(step) if step else 1))
    if not values or min(values) < low or max(values) > high:
        raise ValueError(f"{text!r} is outside {low}-{high}")
    return frozenset(values)


def cron_fire_times(cron: Cron, start: date, days: int):
    """Every firing in [start, start + days), naive, in the cron's own clock."""
    minutes, hours, doms, months, dows = (
        _expand(text, low, high)
        for text, (low, high) in zip(cron.fields(), _CRON_RANGES, strict=True)
    )
    dows = frozenset(0 if d == 7 else d for d in dows)  # 0 and 7 are both Sunday
    dom_any, dow_any = cron.fields()[2] == "*", cron.fields()[4] == "*"
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day.month not in months:
            continue
        dom_hit, dow_hit = day.day in doms, (day.isoweekday() % 7) in dows
        # Vixie cron: when both day fields are restricted, either one matching is enough.
        hit = (dom_hit or dow_hit) if not (dom_any or dow_any) else (dom_hit and dow_hit)
        if hit:
            for hour in sorted(hours):
                for minute in sorted(minutes):
                    yield datetime(day.year, day.month, day.day, hour, minute)


def period_seconds(schedule: Interval | Cron) -> int:
    """The shortest gap between two runs. For a cron, over a 4-year window (leap days included)."""
    if isinstance(schedule, Interval):
        return schedule.seconds
    previous, shortest = None, None
    for fire in cron_fire_times(schedule, date(2001, 1, 1), 4 * 366):
        if previous is not None:
            gap = int((fire - previous).total_seconds())
            if gap == CRON_FLOOR_SECONDS:
                return gap  # nothing is shorter: "* * * * *" stops here, not after ~2M firings
            shortest = gap if shortest is None else min(shortest, gap)
        previous = fire
    if shortest is None:
        raise ValueError(f"cron {schedule.expression!r} fires fewer than twice in four years")
    return shortest


def expire_seconds(spec: JobSpec) -> int:
    """`expires`, or 90% of the period: a run that waited longer is dropped, not run late."""
    return spec.expires or max(1, period_seconds(spec.schedule) * 9 // 10)


def _jittered_start(spec: JobSpec, now: datetime) -> datetime:
    """Interval jobs start at a per-name offset into their period, so not all wake at once."""
    seconds = spec.schedule.seconds
    offset = zlib.crc32(spec.name.encode()) % seconds
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    aligned = epoch + timedelta(seconds=((now - epoch).total_seconds() // seconds) * seconds)
    start = aligned + timedelta(seconds=offset)
    return start if start > now else start + timedelta(seconds=seconds)


# --- The sync -----------------------------------------------------------------------------------


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    # A scheduled job whose name an unowned PeriodicTask already holds: left alone, never adopted.
    conflicts: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.deleted)


def _schedule_fields(spec: JobSpec) -> dict:
    from django_celery_beat.models import CrontabSchedule, IntervalSchedule

    if isinstance(spec.schedule, Interval):
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=spec.schedule.seconds, period=IntervalSchedule.SECONDS
        )
        return {"interval": interval, "crontab": None}
    minute, hour, day_of_month, month_of_year, day_of_week = spec.schedule.fields()
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
        timezone=ZoneInfo(settings.CELERY_TIMEZONE),
    )
    return {"interval": None, "crontab": crontab}


def _desired(spec: JobSpec) -> dict:
    return {
        "task": spec.name,
        "queue": spec.queue,
        "kwargs": json.dumps({}),
        "expire_seconds": expire_seconds(spec),
        "description": spec.description,
        **_schedule_fields(spec),
    }


def _differs(task, desired: dict) -> bool:
    for name, value in desired.items():
        if name in ("interval", "crontab"):
            if getattr(task, f"{name}_id") != (value.pk if value is not None else None):
                return True
        elif getattr(task, name) != value:
            return True
    return False


def sync_schedules(dry_run: bool = False, jobs=None) -> SyncReport:
    from django_celery_beat.models import PeriodicTask, PeriodicTasks

    from core.models import JobSchedule

    specs = (registry.jobs if jobs is None else jobs).specs()
    scheduled = {spec.name: spec for spec in specs if spec.schedule}
    report = SyncReport()
    with transaction.atomic():
        owned = {row.job_name: row for row in JobSchedule.objects.select_related("periodic_task")}
        for name, spec in scheduled.items():
            desired = _desired(spec)
            row = owned.get(name)
            if row is None and PeriodicTask.objects.filter(name=name).exists():
                # PeriodicTask.name is unique, and this row is foreign by the ownership rule (made
                # by hand, restored without core_job_schedule, left from a crontab-era setup).
                # Creating would raise IntegrityError inside post_migrate and fail `migrate`;
                # adopting would overwrite what the registry does not own. Report and go on.
                report.conflicts.append(name)
                logger.error(
                    "core.job.schedule_conflict",
                    extra={"job": name, "reason": "an unowned PeriodicTask holds this name"},
                )
            elif row is None:
                report.created.append(name)
                if not dry_run:
                    extra = {"enabled": spec.enabled_by_default}
                    if isinstance(spec.schedule, Interval):
                        extra["start_time"] = _jittered_start(spec, timezone.now())
                    task = PeriodicTask.objects.create(name=name, **desired, **extra)
                    JobSchedule.objects.create(job_name=name, periodic_task=task)
            elif _differs(row.periodic_task, desired):
                report.updated.append(name)
                if not dry_run:
                    for attr, value in desired.items():
                        setattr(row.periodic_task, attr, value)
                    row.periodic_task.save()
        for name in sorted(set(owned) - set(scheduled)):
            report.deleted.append(name)
            if not dry_run:
                owned[name].periodic_task.delete()  # cascades to the core_job_schedule row
        if report.changed and not dry_run:
            # The DatabaseScheduler only notices changes through this marker (§ 6).
            PeriodicTasks.update_changed()
    return report
