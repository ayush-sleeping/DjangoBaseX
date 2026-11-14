"""
Per-target circuit breaking (JOBS_AND_INTEGRATIONS.md § 19): for any record that stands for a
remote target a sweep calls again and again (a webhook endpoint, a partner account, a feed).

One unreachable target in a fleet sweep multiplies its timeout by every run, until the sweep never
finishes and healthy targets go stale. So after `threshold` consecutive failures (a single blip
benches nothing) the target backs off: base, then doubling, capped. A scheduled sweep skips it
(`due_for_sweep()`); a human-triggered refresh does not ask, because the person is asking exactly
because they fixed something. Success resets it. The state is shown, not only logged:
`backoff_text()`.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone


@dataclass(frozen=True)
class BreakerPolicy:
    threshold: int = 3
    base: timedelta = timedelta(hours=1)
    cap: timedelta = timedelta(hours=24)

    def backoff(self, failures: int) -> timedelta | None:
        """How long to stay away after `failures` consecutive failures; None below threshold."""
        if failures < self.threshold:
            return None
        doublings = failures - self.threshold
        if doublings >= 32:  # 2**32 hours is past any cap
            return self.cap
        return min(self.cap, self.base * (2**doublings))


DEFAULT_BREAKER = BreakerPolicy()


class BreakerQuerySet(models.QuerySet):
    def due_for_sweep(self, now: datetime | None = None):
        """Targets a SCHEDULED sweep may call now. Manual refreshes do not use this."""
        now = now or timezone.now()
        return self.filter(
            models.Q(next_attempt_at__isnull=True) | models.Q(next_attempt_at__lte=now)
        )


class CircuitBreakerMixin(models.Model):
    failure_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=100, blank=True, default="")

    breaker_policy = DEFAULT_BREAKER
    BREAKER_FIELDS = ("failure_count", "next_attempt_at", "last_failure_at", "last_error_code")

    class Meta:
        abstract = True

    def record_failure(self, code: str, *, now: datetime | None = None, save: bool = True) -> None:
        now = now or timezone.now()
        self.failure_count += 1
        self.last_failure_at = now
        self.last_error_code = (code or "")[:100]
        wait = self.breaker_policy.backoff(self.failure_count)
        self.next_attempt_at = now + wait if wait is not None else None
        if save:
            self.save(update_fields=list(self.BREAKER_FIELDS))

    def record_success(self, *, save: bool = True) -> None:
        self.failure_count = 0
        self.next_attempt_at = None
        self.last_error_code = ""
        if save:
            self.save(update_fields=list(self.BREAKER_FIELDS))

    def backoff_text(self, now: datetime | None = None) -> str:
        """ "backed off until 14:20 after 5 failures (timeout)", or "" when it is not."""
        now = now or timezone.now()
        if not self.next_attempt_at or self.next_attempt_at <= now:
            return ""
        return (
            f"backed off until {self.next_attempt_at:%Y-%m-%d %H:%M} UTC after "
            f"{self.failure_count} failures ({self.last_error_code or 'unknown'})"
        )
