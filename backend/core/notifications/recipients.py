"""Recipient and preview callables for core's own purposes (referenced by dotted path)."""

from django.contrib.auth import get_user_model

MAX_MANAGERS = 50


def webhook_managers(object_ref: str, context: dict) -> list[int]:
    """Active users who can manage webhooks: they are the ones who can re-enable the endpoint."""
    users = get_user_model().objects.filter(is_active=True).order_by("id")[:500]
    return [u.pk for u in users if u.has_perm("core.webhooks.manage")][:MAX_MANAGERS]


def webhook_disabled_preview() -> dict:
    return {
        "title": "Webhook endpoint disabled",
        "body": "Endpoint 'Orders receiver' failed 10 deliveries in a row and was switched off.",
        "endpoint_name": "Orders receiver",
        "failures": 10,
    }
