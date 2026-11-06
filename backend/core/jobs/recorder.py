"""
The run record, written from Celery's signals (JOBS_AND_INTEGRATIONS.md § 7).

Every handler is self-guarded: a recording failure is logged at WARNING and dropped, never raised,
because monitoring that can crash the job it monitors is worse than none. Writes go through
settings.JOB_RUN_DB_ALIAS ("monitor": the same database on its own connection), so a queued row is
not rolled back with the publisher's transaction and a failed job's rollback cannot erase the
record of its failure.

Signals arrive from different processes in no guaranteed order (the worker can start a task before
the publisher has written "queued"), so every write is an upsert by task id, and "queued" never
overwrites a later state.
"""

import functools
import logging
import time

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.observability.scrub import default_rules
from core.registry import registry

logger = logging.getLogger("core.jobs.recorder")

MAX_ERROR_LENGTH = 2000
# trigger kwarg (core.jobs.celery.register_task) → JobRun.Trigger. Beat sends none: "schedule".
_TRIGGERS = {"schedule": "schedule", "on_demand": "on_demand", "manual": "manual"}
# Duration is measured here, in the worker, never from row timestamps (§ 7): task id → start.
_STARTED: dict[str, float] = {}
# task id → why the run was skipped (single-flight, § 9), for on_success to record "skipped".
_SKIPPED: dict[str, str] = {}


def _alias() -> str:
    return settings.JOB_RUN_DB_ALIAS


def _model():
    from core.models import JobRun

    return JobRun


def guarded(handler):
    """Never raise out of a signal handler. A dropped record is a WARNING, not a failed job."""

    @functools.wraps(handler)
    def wrapper(*args, **kwargs):
        try:
            handler(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — the recorder must never break the job
            logger.warning(
                "core.job.record_failed",
                extra={"handler": handler.__name__, "error": f"{type(exc).__name__}: {exc}"},
            )

    return wrapper


def _recorded(name: str | None) -> bool:
    return bool(name) and not name.startswith("celery.")


def _unit(name: str) -> str:
    return registry.jobs.get(name).unit if name in registry.jobs else ""


def _trigger(kwargs: dict | None, retries: int = 0) -> str:
    if retries:
        return "retry"
    return _TRIGGERS.get((kwargs or {}).get("trigger"), "schedule")


def error_text(exc: BaseException) -> tuple[str, str]:
    """type + scrubbed, truncated message. Never a traceback: those go to error tracking."""
    message = default_rules().scrub_text(str(exc))[:MAX_ERROR_LENGTH]
    return type(exc).__name__[:200], message


def _upsert(task_id: str, **values) -> None:
    """Write `values` onto the run, creating it if needed. update_or_create is SELECT-then-INSERT:
    when another process (the publisher's on_published, usually) inserts the same task id in
    between, our INSERT loses on the unique key. The row exists by then, so retry ONCE as an
    update. Otherwise a busy system would routinely drop "started" and terminal states, exactly
    when the monitor matters most."""
    runs = _model().objects.using(_alias())
    try:
        with transaction.atomic(using=_alias()):
            runs.update_or_create(task_id=task_id, defaults=values)
    except IntegrityError:
        with transaction.atomic(using=_alias()):
            runs.filter(task_id=task_id).update(**values)


def note_skip(task_id: str, reason: str) -> None:
    """The runner declined to run (single-flight). on_success records the run as skipped."""
    if task_id:
        _SKIPPED[task_id] = reason[:200]


# --- Handlers -----------------------------------------------------------------------------------


@guarded
def on_published(sender=None, headers=None, body=None, routing_key=None, **_):
    headers = headers or {}
    name, task_id = headers.get("task") or sender, headers.get("id")
    if not task_id or not _recorded(name):
        return
    kwargs = body[1] if isinstance(body, (list, tuple)) and len(body) > 1 else {}
    values = {
        "job_name": name,
        "queue": routing_key or "",
        "trigger": _trigger(kwargs, headers.get("retries") or 0),
        "queued_at": timezone.now(),
        "idempotency_key": str((kwargs or {}).get("idempotency_key") or "")[:200],
    }
    JobRun = _model()
    try:
        with transaction.atomic(using=_alias()):
            JobRun.objects.using(_alias()).create(
                task_id=task_id, status=JobRun.Status.QUEUED, unit=_unit(name), **values
            )
    except IntegrityError:
        # The worker got there first: fill in what only the publisher knows, keep its status.
        JobRun.objects.using(_alias()).filter(task_id=task_id).update(
            queued_at=values["queued_at"], trigger=values["trigger"]
        )


@guarded
def on_prerun(sender=None, task_id=None, task=None, kwargs=None, **_):
    if not task_id or not _recorded(getattr(task, "name", None)):
        return
    _STARTED[task_id] = time.perf_counter()
    request = getattr(task, "request", None)
    retries = getattr(request, "retries", 0) or 0
    delivery = getattr(request, "delivery_info", None) or {}
    values = {
        "job_name": task.name,
        "status": "started",
        "started_at": timezone.now(),
        "attempt": retries,
        "unit": _unit(task.name),
        "trigger": _trigger(kwargs, retries),
    }
    if delivery.get("routing_key"):
        values["queue"] = delivery["routing_key"]
    _upsert(task_id, **values)


@guarded
def on_success(sender=None, result=None, **_):
    task_id = getattr(getattr(sender, "request", None), "id", None)
    if not task_id or not _recorded(getattr(sender, "name", None)):
        return
    skipped = _SKIPPED.pop(task_id, None)
    if skipped is not None:
        # Not a failure, and no error: the reason sits where the monitor shows the last message.
        _upsert(
            task_id,
            job_name=sender.name,
            status="skipped",
            finished_at=timezone.now(),
            count=0,
            error_type="",
            error_message=skipped,
        )
        return
    count = result if isinstance(result, int) and not isinstance(result, bool) else None
    _upsert(
        task_id, job_name=sender.name, status="succeeded", finished_at=timezone.now(), count=count
    )


@guarded
def on_failure(sender=None, task_id=None, exception=None, **_):
    if not task_id or not _recorded(getattr(sender, "name", None)):
        return
    error_type, error_message = error_text(exception) if exception else ("", "")
    _upsert(
        task_id,
        job_name=sender.name,
        status="failed",
        finished_at=timezone.now(),
        error_type=error_type,
        error_message=error_message,
    )


@guarded
def on_retry(sender=None, request=None, reason=None, **_):
    task_id = getattr(request, "id", None)
    if not task_id or not _recorded(getattr(sender, "name", None)):
        return
    values = {"job_name": sender.name, "status": "retrying"}
    if isinstance(reason, BaseException):
        values["error_type"], values["error_message"] = error_text(reason)
    _upsert(task_id, **values)


@guarded
def on_revoked(sender=None, request=None, **_):
    task_id = getattr(request, "id", None)
    name = getattr(sender, "name", None) or getattr(request, "task", None)
    if not task_id or not _recorded(name):
        return
    _upsert(task_id, job_name=name, status="revoked", finished_at=timezone.now())


@guarded
def on_postrun(sender=None, task_id=None, **_):
    started = _STARTED.pop(task_id, None) if task_id else None
    if started is None or not _recorded(getattr(sender, "name", None)):
        return
    duration_ms = max(0, round((time.perf_counter() - started) * 1000))
    JobRun = _model()
    JobRun.objects.using(_alias()).filter(task_id=task_id).update(duration_ms=duration_ms)


@guarded
def on_unknown(sender=None, name=None, id=None, exc=None, **_):  # noqa: A002 — Celery's name
    if not id:
        return
    error_type, error_message = error_text(exc) if exc else ("", "")
    _upsert(
        id,
        job_name=(name or "unknown")[:150],
        status="dead",
        finished_at=timezone.now(),
        error_type=error_type or "UnregisteredTask",
        error_message=error_message or f"no task named {name!r} is registered",
    )


@guarded
def on_rejected(sender=None, message=None, exc=None, **_):
    headers = getattr(message, "headers", None) or {}
    task_id, name = headers.get("id"), headers.get("task") or "unknown"
    if not task_id:
        return
    error_type, error_message = error_text(exc) if exc else ("Rejected", "")
    _upsert(
        task_id,
        job_name=name[:150],
        status="dead",
        finished_at=timezone.now(),
        error_type=error_type,
        error_message=error_message,
    )


def connect() -> None:
    from celery import signals

    for signal, handler in (
        (signals.after_task_publish, on_published),
        (signals.task_prerun, on_prerun),
        (signals.task_success, on_success),
        (signals.task_failure, on_failure),
        (signals.task_retry, on_retry),
        (signals.task_revoked, on_revoked),
        (signals.task_postrun, on_postrun),
        (signals.task_unknown, on_unknown),
        (signals.task_rejected, on_rejected),
    ):
        signal.connect(handler, weak=False, dispatch_uid=f"core.jobs.recorder.{handler.__name__}")
