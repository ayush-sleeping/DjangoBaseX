"""The users module's background jobs (JOBS_AND_INTEGRATIONS.md § 1), registered in ready()."""

from core.jobs import Cron, JobContext, JobSpec

AUTH_CLEANUP = JobSpec(
    name="users.auth_cleanup",
    func="users.jobs.auth_cleanup",
    owner_module="users",
    description=(
        "Deletes login attempts, dead sessions and used or expired reset tokens past their "
        "retention (AUTH_BLUEPRINT § 19.2). If it stops, users_login_attempt grows with attack "
        "traffic, not with users, and lockout queries slow down with it."
    ),
    queue="bulk",
    schedule=Cron("17 3 * * *"),  # daily, 03:17 UTC: off the hour on purpose
    # Not destructive in § 1's sense: it removes only expired auth bookkeeping, never evidence or
    # the audit trail, and leaving it off is the defect TECH_DEBT DB-16 recorded.
    destructive=False,
    idempotent=True,  # a second run finds nothing past retention (tests/core/jobs)
    time_limit=900,
    soft_time_limit=840,
)


def auth_cleanup(ctx: JobContext) -> int:
    from core.retention import engine
    from core.retention.jobs import log_results

    return log_results(ctx, engine.run(owner="users", scheduled=True))
