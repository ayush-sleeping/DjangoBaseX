"""
The queue and schedule doctors (JOBS_AND_INTEGRATIONS.md § 8): `doctor --only queue|schedule`.

Both delegate: configuration problems come from the real system check, job and queue state from
core.jobs.health.report() (the same function the "jobs" health check uses), schedule drift from a
dry-run of the real sync. Nothing here re-models any of it.
"""

import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.registry import ADVISORY, FAILURE, Finding, registry

from . import health
from .schedules import period_seconds, sync_schedules

PEEK_LIMIT = 100  # waiting messages inspected per queue for unregistered task names


def queue_doctor() -> list[Finding]:
    from core.checks import check_celery_config

    findings = [
        Finding(FAILURE, f"queue.config.{error.id}", "celery", error.msg, remedy=error.hint or "")
        for error in check_celery_config(None)
    ]
    report = health.report()
    for queue in report.queues:
        if queue.stalled:
            findings.append(
                Finding(
                    FAILURE,
                    "queue.stalled",
                    queue.name,
                    f"{queue.backlog} waiting; the oldest since "
                    f"{queue.oldest_queued_at:%Y-%m-%d %H:%M} UTC",
                    remedy=f"start a worker consuming {queue.name!r} (celery worker -Q …)",
                )
            )
        elif not queue.alive:
            findings.append(
                Finding(
                    FAILURE,
                    "queue.no_consumer",
                    queue.name,
                    f"{queue.backlog} waiting and no job started recently",
                    remedy=f"check that a worker is running and consumes {queue.name!r}",
                )
            )
    window = timezone.now() - timedelta(minutes=health.queue_policy().worker_seen_window_minutes)
    dead = health._runs().filter(status="dead", finished_at__gte=window)
    for name in sorted(set(dead.values_list("job_name", flat=True))):
        findings.append(
            Finding(
                FAILURE,
                "queue.dead_task",
                name,
                f"a worker received {name!r}, which is not a registered task",
                remedy="deploy the code that registers it, or purge the messages",
            )
        )
    findings += _peek_unregistered()
    return findings


def _peek_unregistered() -> list[Finding]:
    """Unregistered task names waiting in the broker. Redis only, read-only (LRANGE)."""
    broker = (settings.CELERY_BROKER_URL or "").lower()
    if not broker.startswith(("redis://", "rediss://")):
        return [
            Finding(
                ADVISORY,
                "queue.not_inspected",
                "broker",
                "waiting messages were not inspected: only a Redis broker can be read without "
                "consuming them",
            )
        ]
    from celery import current_app
    from kombu import Connection

    from .topology import declared_queues

    findings = []
    with Connection(settings.CELERY_BROKER_URL) as conn:
        client = conn.default_channel.client
        for queue in sorted(declared_queues()):
            names = set()
            for raw in client.lrange(queue, 0, PEEK_LIMIT - 1):
                try:
                    names.add(json.loads(raw)["headers"]["task"])
                except (ValueError, KeyError, TypeError):
                    names.add("<unreadable message>")
            for name in sorted(names - set(current_app.tasks)):
                findings.append(
                    Finding(
                        FAILURE,
                        "queue.unregistered_waiting",
                        f"{queue}:{name}",
                        f"{queue!r} holds messages for {name!r}, which no worker can run",
                        remedy="deploy the code that registers it, or purge those messages",
                    )
                )
    return findings


def schedule_doctor() -> list[Finding]:
    from django_celery_beat.models import PeriodicTask

    from core.models import JobSchedule

    findings = []
    drift = sync_schedules(dry_run=True)
    for name in drift.conflicts:
        findings.append(
            Finding(
                FAILURE,
                "schedule.conflict",
                name,
                "a PeriodicTask with this name exists and the registry does not own it",
                remedy="delete or rename it, then run manage.py sync_schedules",
            )
        )
    for action in ("created", "updated", "deleted"):
        for name in getattr(drift, action):
            findings.append(
                Finding(
                    FAILURE,
                    "schedule.not_synced",
                    name,
                    f"beat's schedule is behind the registry: a sync would {action[:-1]} it",
                    remedy="run manage.py sync_schedules (migrate also runs it)",
                )
            )
    owned = {row.job_name: row for row in JobSchedule.objects.all()}
    now = timezone.now()
    grace = timedelta(minutes=health.queue_policy().stall_threshold_minutes)
    report = health.report(now)
    for job in report.jobs:
        spec = registry.jobs.get(job.name)
        if spec.schedule is None:
            continue
        if job.state in (health.FAILING, health.OVERDUE):
            findings.append(
                Finding(
                    FAILURE,
                    f"schedule.{job.state}",
                    job.name,
                    job.reason + (f" ({job.last_error})" if job.last_error else ""),
                    remedy="read the job's last error; check the worker and beat are running",
                )
            )
        elif job.state == health.NEVER_RUN and job.name in owned:
            # A new deploy is not an incident; a schedule that has existed a full period plus the
            # grace and never ran is.
            due_by = owned[job.name].created_at + timedelta(seconds=period_seconds(spec.schedule))
            if now > due_by + grace:
                findings.append(
                    Finding(
                        FAILURE,
                        "schedule.never_run",
                        job.name,
                        f"scheduled since {owned[job.name].created_at:%Y-%m-%d %H:%M} UTC and "
                        "never started",
                        remedy="check that beat is running (exactly one) and a worker consumes "
                        f"{spec.queue!r}",
                    )
                )
    owned_tasks = {row.periodic_task_id for row in owned.values()}
    for task in PeriodicTask.objects.exclude(pk__in=owned_tasks).exclude(
        name__startswith="celery."
    ):
        findings.append(
            Finding(
                ADVISORY,
                "schedule.unowned",
                task.name,
                f"beat row {task.name!r} ({task.task}) is not owned by the job registry",
                remedy="declare it as a JobSpec, or delete it if it is stale",
            )
        )
    return findings
