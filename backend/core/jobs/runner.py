"""
execute(): the one place a registered job runs (JOBS_AND_INTEGRATIONS.md § 2).

Every runner calls this, so nothing job-specific lives in a loop. The run record (§ 7, core_job_run)
arrives with BUILD_ORDER 7.2 and is written here, not in the Celery wrapper.
"""

import inspect
from collections.abc import Callable
from importlib import import_module

from .spec import JobContext, JobSpec


def resolve(spec: JobSpec) -> Callable[[JobContext], int]:
    """The spec's callable. ImportError/AttributeError when `func` names nothing (dbx.jobs.E004)."""
    module_path, _, attr = spec.func.rpartition(".")
    return getattr(import_module(module_path), attr)


def signature_problem(func: object) -> str | None:
    """Why `func` is not `def run(ctx) -> int`, or None when it is."""
    if not callable(func):
        return "is not callable"
    try:
        params = list(inspect.signature(func).parameters.values())
    except (TypeError, ValueError):
        return "has no inspectable signature"
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    required = [p for p in params if p.default is inspect.Parameter.empty]
    if len(params) != 1 or len(required) != 1 or params[0].kind not in positional:
        return "must take exactly one positional argument, the JobContext"
    return None


def execute(spec: JobSpec, ctx: JobContext) -> int:
    """Run `spec` once and return its count. Exceptions propagate to the runner that called it."""
    count = resolve(spec)(ctx)
    if not isinstance(count, int) or isinstance(count, bool):
        raise TypeError(f"job {spec.name!r} returned {count!r}; a job returns an int ({spec.unit})")
    ctx.logger.info(
        "core.job.finished",
        extra={"job": spec.name, "run_id": ctx.run_id, "count": count, "unit": spec.unit},
    )
    return count
