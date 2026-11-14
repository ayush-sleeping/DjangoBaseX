"""The retention job's body (BUILD_ORDER 7.5). Policies, windows and gates are the engine's."""

from core.jobs import JobContext

from . import engine


def log_results(ctx: JobContext, results: list[engine.PolicyResult]) -> int:
    for result in results:
        ctx.logger.info(
            "core.retention.policy",
            extra={
                "policy": result.key,
                "state": result.state,
                "deleted": result.deleted,
                "truncated": result.truncated,
            },
        )
    return sum(result.deleted for result in results)


def run_retention(ctx: JobContext) -> int:
    return log_results(ctx, engine.run(scheduled=True))
