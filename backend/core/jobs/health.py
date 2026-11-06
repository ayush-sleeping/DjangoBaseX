"""
Is the background system actually working? (JOBS_AND_INTEGRATIONS.md § 8)

One implementation behind every rendering: the queue and schedule doctors, the "jobs" health check
and, later, the Job Monitor API. The failure mode this exists for is a worker that is not running,
which looks exactly like a healthy, quiet system. Every signal here is designed to tell them apart.

Per job, in precedence order: disabled > never_run > failing > overdue > ok. Alongside it,
worker_seen_recently (any start within the window) and per-queue liveness (recent activity OR an
empty queue). `now` is always passed in, so the arithmetic is testable without moving the clock.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from core.registry import Cron, Interval, JobSpec, registry
from core.settings_registry import Int, meta

from .schedules import period_seconds, previous_fire
from .topology import declared_queues

DISABLED, NEVER_RUN, FAILING, OVERDUE, OK = "disabled", "never_run", "failing", "overdue", "ok"
GREEN, RED = "green", "red"
# An Interval job is overdue when its last start is older than this many periods (§ 8).
OVERDUE_PERIODS = 3


@dataclass(frozen=True)
class QueuePolicy:
    """operations.queue.* (CONFIGURATION.md § 9). Registered by CoreConfig."""

    stall_threshold_minutes: int = field(
        default=15,
        metadata=meta(
            Int(min=1, max=1440),
            label="Minutes before a waiting job means a stalled queue",
            description=(
                "A queue whose oldest waiting job is older than this is reported stalled, and a "
                "scheduled job not started this long after its due time is overdue. Lower finds a "
                "dead worker sooner and flags slow-but-working queues more often."
            ),
            changed_by_event="A false alarm on a busy queue, or a dead worker noticed too late",
            used_by=("Job health", "doctor --only queue", "doctor --only schedule"),
        ),
    )
    worker_seen_window_minutes: int = field(
        default=15,
        metadata=meta(
            Int(min=1, max=1440),
            label='Minutes a started job counts as "worker seen recently"',
            description=(
                "With no job started in this window, the worker is reported unseen. A queue with "
                "waiting jobs and no start in the window has no live consumer."
            ),
            changed_by_event="Jobs that legitimately run less often than this",
            used_by=("Job health", "doctor --only queue"),
        ),
    )


@dataclass(frozen=True)
class JobHealth:
    name: str
    state: str
    queue: str
    schedule: str
    last_started_at: datetime | None
    last_status: str
    last_error: str
    next_due: datetime | None
    reason: str


@dataclass(frozen=True)
class QueueHealth:
    name: str
    backlog: int
    oldest_queued_at: datetime | None
    last_started_at: datetime | None
    alive: bool
    stalled: bool


@dataclass(frozen=True)
class MonitorReport:
    now: datetime
    status: str
    worker_seen_recently: bool
    jobs: tuple[JobHealth, ...]
    queues: tuple[QueueHealth, ...]
    failed_runs: int
    reasons: tuple[str, ...] = field(default=())


def _runs():
    from core.models import JobRun

    return JobRun.objects.using(settings.JOB_RUN_DB_ALIAS)


def queue_policy() -> QueuePolicy:
    from core.settings_service import resolve

    return resolve(QueuePolicy)


def _schedule_text(spec: JobSpec) -> str:
    if isinstance(spec.schedule, Interval):
        return f"every {spec.schedule.seconds}s"
    if isinstance(spec.schedule, Cron):
        return f"cron {spec.schedule.expression}"
    return "on demand"


def _enabled(spec: JobSpec, beat_enabled: dict[str, bool]) -> bool:
    """The owned beat row's switch when there is one (an operator's toggle); else the spec."""
    return beat_enabled.get(spec.name, spec.enabled_by_default)


def _beat_enabled() -> dict[str, bool]:
    from core.models import JobSchedule

    return {
        row.job_name: row.periodic_task.enabled
        for row in JobSchedule.objects.select_related("periodic_task")
    }


def job_health(spec: JobSpec, now: datetime, *, enabled: bool, policy: QueuePolicy) -> JobHealth:
    runs = _runs().for_job(spec.name)
    last_start = runs.exclude(started_at=None).order_by("-started_at").first()
    last_terminal = runs.terminal().order_by("-finished_at", "-id").first()
    last_started_at = last_start.started_at if last_start else None
    next_due, overdue_reason = _due(spec, now, last_started_at, policy)

    def health(state: str, reason: str) -> JobHealth:
        return JobHealth(
            name=spec.name,
            state=state,
            queue=spec.queue,
            schedule=_schedule_text(spec),
            last_started_at=last_started_at,
            last_status=last_terminal.status if last_terminal else "",
            last_error=(
                f"{last_terminal.error_type}: {last_terminal.error_message}"
                if last_terminal and last_terminal.error_type
                else ""
            ),
            next_due=next_due,
            reason=reason,
        )

    if not enabled:
        return health(DISABLED, "switched off")
    if last_started_at is None:
        return health(NEVER_RUN, "no run has ever started")
    if last_terminal is not None and last_terminal.status in ("failed", "dead"):
        return health(FAILING, f"the last run {last_terminal.status}")
    if overdue_reason:
        return health(OVERDUE, overdue_reason)
    return health(OK, "")


def _due(spec, now, last_started_at, policy) -> tuple[datetime | None, str]:
    """(next due, why it is overdue or ""). Unscheduled jobs are never overdue."""
    if isinstance(spec.schedule, Interval):
        period = timedelta(seconds=spec.schedule.seconds)
        if last_started_at is None:
            return None, ""
        late_after = last_started_at + OVERDUE_PERIODS * period
        if now > late_after:
            return last_started_at + period, (
                f"no start for {int((now - last_started_at).total_seconds())}s, more than "
                f"{OVERDUE_PERIODS} × {spec.schedule.seconds}s"
            )
        return last_started_at + period, ""
    if isinstance(spec.schedule, Cron):
        fired = previous_fire(spec.schedule, now)
        grace = timedelta(minutes=policy.stall_threshold_minutes)
        next_due = fired + timedelta(seconds=period_seconds(spec.schedule))
        if last_started_at is not None and last_started_at < fired and now > fired + grace:
            return next_due, f"due at {fired.isoformat()} and not started within {grace}"
        return next_due, ""
    return None, ""


def queue_health(name: str, now: datetime, policy: QueuePolicy) -> QueueHealth:
    runs = _runs().filter(queue=name)
    queued = runs.queued()
    oldest = queued.order_by("queued_at").values_list("queued_at", flat=True).first()
    last_start = (
        runs.exclude(started_at=None)
        .order_by("-started_at")
        .values_list("started_at", flat=True)
        .first()
    )
    window = timedelta(minutes=policy.worker_seen_window_minutes)
    backlog = queued.count()
    recent = last_start is not None and last_start >= now - window
    stalled = oldest is not None and oldest < now - timedelta(
        minutes=policy.stall_threshold_minutes
    )
    return QueueHealth(
        name=name,
        backlog=backlog,
        oldest_queued_at=oldest,
        last_started_at=last_start,
        alive=recent or backlog == 0,  # an idle queue with no backlog is healthy by definition
        stalled=stalled,
    )


def report(now: datetime | None = None, jobs=None) -> MonitorReport:
    now = now or timezone.now()
    jobs = registry.jobs if jobs is None else jobs
    policy = queue_policy()
    beat_enabled = _beat_enabled()
    job_rows = tuple(
        job_health(spec, now, enabled=_enabled(spec, beat_enabled), policy=policy)
        for spec in jobs.specs()
    )
    queue_rows = tuple(queue_health(name, now, policy) for name in sorted(declared_queues(jobs)))
    window = timedelta(minutes=policy.worker_seen_window_minutes)
    worker_seen = _runs().started_since(now - window).exists()

    reasons = [
        f"job {j.name} is {j.state}: {j.reason}" for j in job_rows if j.state in (FAILING, OVERDUE)
    ]
    reasons += [
        f"queue {q.name} is stalled: oldest queued at {q.oldest_queued_at.isoformat()}"
        for q in queue_rows
        if q.stalled
    ]
    reasons += [
        f"queue {q.name} has {q.backlog} waiting and no recent consumer"
        for q in queue_rows
        if not q.alive and not q.stalled
    ]
    return MonitorReport(
        now=now,
        status=RED if reasons else GREEN,
        worker_seen_recently=worker_seen,
        jobs=job_rows,
        queues=queue_rows,
        failed_runs=_runs().failed().count(),
        reasons=tuple(reasons),
    )
