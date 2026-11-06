"""
The Reconciler base (JOBS_AND_INTEGRATIONS.md § 11): the job that goes back and asks.

A subclass gives `queryset()` (the rows needing attention, re-checked per row) and
`reconcile(obj) -> Result`. The base supplies what every hand-written copy got wrong:

- **Per-row commit.** Each row runs in its own transaction, so progress is banked as it goes; a
  SoftTimeLimitExceeded stops the pass and returns what is done instead of losing it.
- **Re-check under a row lock.** Each id is re-read through queryset() with
  select_for_update(skip_locked=True): a row that changed or that another worker holds is skipped.
- **Drift mutates nothing.** A DRIFT result rolls the row's transaction back, whatever reconcile()
  touched, and records a finding for a human. FIXED/UNCHANGED auto-clear the reconciler's kinds.
- **A cap is reported, never mistaken for clean**: "batch limit reached; N remain".
- **A resumable reconciler** keeps its cursor in core_job_state, a database row.
"""

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from core import findings

logger = logging.getLogger("core.jobs.reconciler")

FIXED, UNCHANGED, DRIFT, SKIP = "fixed", "unchanged", "drift", "skip"


@dataclass(frozen=True)
class Result:
    outcome: str
    kind: str = ""  # DRIFT: the registered finding kind
    details: dict = field(default_factory=dict)
    reason: str = ""  # SKIP: why

    @classmethod
    def fixed(cls):
        return cls(FIXED)

    @classmethod
    def unchanged(cls):
        return cls(UNCHANGED)

    @classmethod
    def drift(cls, kind: str, details: dict | None = None):
        return cls(DRIFT, kind=kind, details=details or {})

    @classmethod
    def skip(cls, reason: str):
        return cls(SKIP, reason=reason)


@dataclass
class Report:
    seen: int = 0
    fixed: int = 0
    unchanged: int = 0
    drift: int = 0
    skipped: int = 0
    capped: bool = False
    remaining: int = 0
    stopped_early: bool = False


class Reconciler:
    name: str = ""  # also the JobSpec name
    batch_size: int = 50
    resumable: bool = False  # True: walk by primary key from the cursor in core_job_state
    kinds: tuple[str, ...] = ()  # the drift kinds this reconciler raises; cleared on convergence

    def queryset(self):
        raise NotImplementedError

    def reconcile(self, obj) -> Result:
        raise NotImplementedError

    def give_up(self, obj, reason: str) -> None:
        findings.raise_or_touch(f"{self.name}.gave_up", obj, details={"reason": reason})

    # --- The loop ---------------------------------------------------------------------------

    def _state(self):
        from core.models import JobState

        return JobState.objects.get_or_create(name=self.name)[0]

    def run(self, ctx=None) -> Report:
        from celery.exceptions import SoftTimeLimitExceeded

        report = Report()
        state = self._state() if self.resumable else None
        after = (state.cursor or {}).get("after") if state else None
        ids_query = self.queryset().order_by("pk")
        if after is not None:
            ids_query = ids_query.filter(pk__gt=after)
        ids = list(ids_query.values_list("pk", flat=True)[: self.batch_size + 1])
        if len(ids) > self.batch_size:
            ids = ids[: self.batch_size]
            report.capped = True
        try:
            for pk in ids:
                if ctx is not None and ctx.stop_requested():
                    report.stopped_early = True
                    break
                self._one(pk, report)
                if state is not None:
                    state.cursor = {"after": pk}
                    state.save(update_fields=["cursor", "updated_at"])
        except SoftTimeLimitExceeded:
            report.stopped_early = True
            logger.warning(
                "core.reconciler.time_limit",
                extra={"job": self.name, "done": report.seen, "note": "progress banked"},
            )
        if report.capped and not report.stopped_early:
            report.remaining = ids_query.filter(pk__gt=ids[-1]).count()
            logger.warning(
                "core.reconciler.capped",
                extra={
                    "job": self.name,
                    "batch_size": self.batch_size,
                    "remaining": report.remaining,
                },
            )
        if state is not None and not report.capped and not report.stopped_early:
            state.cursor = None  # a full pass: start from the beginning next time
            state.last_success_at = timezone.now()
            state.save(update_fields=["cursor", "last_success_at", "updated_at"])
        return report

    def _one(self, pk, report: Report) -> None:
        drift = None
        with transaction.atomic():
            obj = self.queryset().select_for_update(skip_locked=True).filter(pk=pk).first()
            if obj is None:
                return  # converged since the id was read, or another worker holds it
            report.seen += 1
            result = self.reconcile(obj)
            if result.outcome == DRIFT:
                # Exists and differs: mutate nothing. Whatever reconcile() wrote is undone.
                transaction.set_rollback(True)
                drift = (obj, result)
            elif result.outcome in (FIXED, UNCHANGED):
                setattr(report, result.outcome, getattr(report, result.outcome) + 1)
                for kind in self.kinds:
                    findings.clear(kind, obj)
            else:
                report.skipped += 1
                logger.info(
                    "core.reconciler.skipped",
                    extra={"job": self.name, "object_id": str(pk), "reason": result.reason},
                )
        if drift is not None:
            obj, result = drift
            report.drift += 1
            with transaction.atomic():
                findings.raise_or_touch(result.kind, obj, details=result.details)


def run_registered(ctx) -> int:
    """The func of every JobSpec a ReconcilerSpec generates: look the reconciler up by job name."""
    from core.registry import registry

    from .runner import resolve_path

    spec = registry.reconcilers.get(ctx.job_name)
    reconciler = resolve_path(spec.reconciler)()
    report = reconciler.run(ctx)
    return report.seen
