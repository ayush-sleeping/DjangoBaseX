"""
What a job is handed, and what it declares (JOBS_AND_INTEGRATIONS.md § 1).

The declarations (JobSpec, Interval, Cron) live in core.registry, which stays standard library only,
and are re-exported here so a module imports everything job-shaped from core.jobs.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from core.registry import Cron, Interval, JobSpec

__all__ = ["RESERVED_KWARGS", "Cron", "Interval", "JobContext", "JobSpec"]

# The generated task's own keyword arguments (core.jobs.celery.register_task). A job's params can
# never use these names: enqueue() refuses them rather than let a caller forge them.
RESERVED_KWARGS = frozenset({"trigger", "idempotency_key"})


def _never() -> bool:
    return False


@dataclass(frozen=True)
class JobContext:
    """
    The one argument every job takes: `def run(ctx: JobContext) -> int`.

    `stop_requested()` is the probe a long job polls between batches. A Celery worker stops through
    its soft time limit (SoftTimeLimitExceeded), so under Celery the probe answers False until a
    runner that can request a stop exists.
    """

    run_id: str
    job_name: str
    trigger: str = "schedule"  # "schedule" | "on_demand" | "manual" | "retry"
    idempotency_key: str | None = None
    # The enqueue() kwargs: primitive ids and small scalars only (§ 4); the job re-reads its rows.
    params: dict[str, int | str | bool | None] = field(default_factory=dict)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("core.jobs"))
    stop_requested: Callable[[], bool] = _never
