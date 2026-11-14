"""Who an ops message reaches, by data: the purpose's routes (admin-edited) and the people who can
edit those routes. No address, channel id or URL lives in code (§ 1, § 14)."""

from django.contrib.auth import get_user_model

from core.models import NotificationRoute

from .kinds import PURPOSE_ALERT, PURPOSE_DIGEST

MAX_RECIPIENTS = 50


def ops_recipients(object_ref: str, context: dict) -> list[int]:
    """Active users who administer notification routing: they can see and fix an ops alert."""
    users = get_user_model().objects.filter(is_active=True).order_by("id")[:500]
    return [u.pk for u in users if u.has_perm("core.notifications.manage")][:MAX_RECIPIENTS]


def has_destination() -> bool:
    """True when an ops message would reach anyone: an active route or a resolvable person."""
    routed = NotificationRoute.objects.filter(
        purpose_code__in=(PURPOSE_ALERT, PURPOSE_DIGEST), is_active=True
    ).exists()
    return routed or bool(ops_recipients("", {}))


def alert_preview() -> dict:
    return {
        "title": "Billing queue stalled",
        "body": "Oldest job queued 42 minutes ago.\nCheck that a worker consumes the queue.",
    }


def digest_preview() -> dict:
    return {
        "title": "Ops digest: 2 held alerts, 1 open incident",
        "body": "Held since the last digest:\n- Queue slow\n- Job late\n\nNext digest 17:00.",
    }
