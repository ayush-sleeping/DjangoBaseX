"""
Instant or digest (§ 15): a pure function over the ledger and the settings. The ops overview
(deferred) calls this same function to explain itself.

Order, every stop with its reason: disabled > no destination > (not on the allow-list: held for
the digest) > cooldown > quiet hours > storm cap > send. A recovery is never cooled down.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from core.models import OpsAlert

from . import quiet_hours
from .kinds import (
    HELD_DIGEST,
    HELD_QUIET,
    HELD_STORM,
    INSTANT_KINDS,
    SKIP_ALREADY_HELD,
    SKIP_COOLDOWN,
    SKIP_DISABLED,
    SKIP_NO_DESTINATION,
)
from .recipients import has_destination

Decision = OpsAlert.Decision


@dataclass(frozen=True)
class Outcome:
    decision: str
    reason: str = ""


def cooldown_minutes(kind: str, p) -> int:
    return getattr(p, f"cooldown_minutes_{kind}")


def decide(kind: str, subject_key: str, event: str = "problem", now: datetime | None = None):
    now = now or timezone.now()
    p = quiet_hours.policy()
    if not p.enabled:
        return Outcome(Decision.SKIPPED, SKIP_DISABLED)
    if not has_destination():
        return Outcome(Decision.SKIPPED, SKIP_NO_DESTINATION)
    ledger = OpsAlert.objects.filter(subject_key=subject_key)
    if kind not in {k.value for k in INSTANT_KINDS}:  # an unknown kind is held, never sent
        if (
            event == "problem"
            and ledger.filter(
                decision=Decision.HELD, released_at__isnull=True, event=event
            ).exists()
        ):
            return Outcome(Decision.SKIPPED, SKIP_ALREADY_HELD)
        return Outcome(Decision.HELD, HELD_DIGEST)
    if event == "problem":
        since = now - timedelta(minutes=cooldown_minutes(kind, p))
        if ledger.filter(
            decision__in=(Decision.SENT, Decision.HELD), event=event, created_at__gte=since
        ).exists():
            return Outcome(Decision.SKIPPED, SKIP_COOLDOWN)
    if quiet_hours.in_quiet_hours(now, p):
        return Outcome(Decision.HELD, HELD_QUIET)
    sent = OpsAlert.objects.filter(
        decision=Decision.SENT,
        kind__in=[k.value for k in INSTANT_KINDS],
        created_at__gte=now - timedelta(hours=1),
    ).count()
    if sent >= p.max_instant_per_hour:
        return Outcome(Decision.HELD, HELD_STORM)
    return Outcome(Decision.SENT)
