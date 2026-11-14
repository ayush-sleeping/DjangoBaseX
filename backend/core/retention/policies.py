"""
Core's own retention policies and the daily job that applies every registered policy, registered
from CoreConfig.ready() (BUILD_ORDER 7.5). A module registers its own beside its models (users:
users/retention.py); this file is only what core owns.
"""

from django.db.models import Q

from core.registry import Cron, JobSpec, Registry, RetentionPolicy
from core.retention import register

JOB_NAME = "core.retention"

# core_job_run: terminal rows only. queued, started and retrying are live state and never match.
COMPLETED = ("succeeded", "skipped", "revoked")
FAILED = ("failed", "dead")

POLICIES = (
    RetentionPolicy(
        key="core.job_run_completed",
        model="core.JobRun",
        timestamp_field="finished_at",
        description="Runs of background jobs that finished without an error.",
        data_class="operational_log",
        max_age_days=14,
        min_age_days=1,
        filter=Q(status__in=COMPLETED),
        max_rows=200_000,  # a frequent job (the outbox drain) fills the table by volume, not age
    ),
    RetentionPolicy(
        key="core.job_run_failed",
        model="core.JobRun",
        timestamp_field="finished_at",
        description="Runs of background jobs that failed or could not be found.",
        data_class="operational_log",
        max_age_days=90,
        min_age_days=7,
        filter=Q(status__in=FAILED),
        max_rows=50_000,  # grows fastest exactly when something is wrong
    ),
    RetentionPolicy(
        key="core.activity_log",
        model="core.ActivityLog",
        timestamp_field="created_at",
        description="The audit log: evidence of who did what.",
        data_class="evidence",
        max_age_days=365,  # a year covers an annual audit cycle; shorter is the owner's decision
        min_age_days=90,
        requires_opt_in=True,  # core never silently truncates an audit trail (AUTH_BLUEPRINT 19.2)
    ),
)

JOB = JobSpec(
    name=JOB_NAME,
    func="core.retention.jobs.run_retention",
    owner_module="core",
    description=(
        "Applies every registered retention policy: deletes rows past their window, then past "
        "their row cap. If it stops, core_job_run, the login-attempt table and every other "
        "registered log grow without bound, fastest when something is wrong."
    ),
    queue="bulk",
    schedule=Cron("43 3 * * *"),  # daily, 03:43 UTC: off the hour and clear of users.auth_cleanup
    # Not destructive in JOBS § 1's sense: evidence (the audit log) is opt-in per policy and stays
    # untouched until an operator turns its `.enabled` setting on, which is the recorded decision.
    destructive=False,
    idempotent=True,  # a second run finds nothing past its window (tests/core/test_retention.py)
    time_limit=1800,
    soft_time_limit=1680,
)


def register_core_retention(registry: Registry) -> None:
    for policy in POLICIES:
        register(registry, policy)
    registry.jobs.register(JOB)
