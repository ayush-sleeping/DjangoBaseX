"""
Progressive lockout (AUTH_BLUEPRINT § 6.2 step 2, A17). A pure query over users_login_attempt: no
cache, so a cache flush or a second worker cannot reset anyone's count.

A key (identifier or IP) is locked when LOCKOUT_THRESHOLD counted failures fall within one
LOCKOUT_WINDOW of each other, until the latest of them + the lock duration. The window is measured
across the burst, not back from now: measured from now, the oldest failure of the burst ages out
first and the lock lifts early (after a few seconds, if the burst was slow).

Counted failures exclude failure_reason="locked", so attempts made while locked never extend the
lock. For an identifier, only failures since its most recent success count: signing in resets it.
An IP has no such reset (one person's success says nothing about the rest of a shared NAT), and its
threshold is ×5 for the same reason.

Each lock in the last 24h doubles the next one: DURATION × 2^(k-1), k = counted failures in 24h //
threshold, capped at 24h.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import LoginAttempt

IP_THRESHOLD_FACTOR = 5


class LockedOut(Exception):
    """Too many recent failures for this address or IP (A17). The secret is not even checked."""


HISTORY = timedelta(hours=24)
MAX_DURATION = timedelta(hours=24)


def is_locked(identifier: str, ip: str | None) -> bool:
    """`identifier` must already be normalised (users.models.user.normalize_email)."""
    now = timezone.now()
    threshold = settings.LOCKOUT_THRESHOLD

    failures = LoginAttempt.objects.filter(succeeded=False).exclude(
        failure_reason=LoginAttempt.FailureReason.LOCKED
    )
    since = now - HISTORY

    last_success = (
        LoginAttempt.objects.filter(identifier=identifier, succeeded=True, created_at__gte=since)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    ident_failures = failures.filter(identifier=identifier, created_at__gte=since)
    if last_success is not None:
        ident_failures = ident_failures.filter(created_at__gt=last_success)
    if _locked(ident_failures, threshold, now):
        return True

    if ip is None:
        return False
    ip_failures = failures.filter(ip=ip, created_at__gte=since)
    return _locked(ip_failures, threshold * IP_THRESHOLD_FACTOR, now)


def _locked(failures, threshold: int, now) -> bool:
    burst = list(failures.order_by("-created_at").values_list("created_at", flat=True)[:threshold])
    if len(burst) < threshold:
        return False
    latest, oldest = burst[0], burst[-1]
    if latest - oldest > timedelta(seconds=settings.LOCKOUT_WINDOW):
        return False
    return now < latest + _duration(failures.count() // threshold)


def _duration(k: int) -> timedelta:
    base = timedelta(seconds=settings.LOCKOUT_DURATION)
    # Cap the exponent before computing it: k is attacker-driven.
    doublings = max(k, 1) - 1
    if doublings >= 32:
        return MAX_DURATION
    return min(base * 2**doublings, MAX_DURATION)
