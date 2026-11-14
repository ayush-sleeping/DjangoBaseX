"""
Notification administration: the one writer for routes, the matrix and per-user preferences
(NOTIFICATIONS_AND_ALERTING.md §§ 1, 4, 5). Views stay thin; this validates and audits.
"""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from core import audit
from core.models import (
    NotificationDelivery,
    NotificationPreference,
    NotificationPurposeState,
    NotificationRoute,
    NotificationSetting,
)
from core.registry import registry

from . import engine

MAX_ADDRESSES = 20


class NotificationAdminError(Exception):
    code = "invalid"


class InvalidRoute(NotificationAdminError):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


class Locked(NotificationAdminError):
    """A mandatory purpose cannot be switched off."""

    code = "mandatory"


def purpose_of(code: str):
    if code not in registry.notification_purposes:
        raise InvalidRoute("purpose_code", "Unknown notification purpose.")
    return registry.notification_purposes.get(code)


def validate_target(channel: str, target) -> dict:
    if channel not in registry.notification_channels:
        raise InvalidRoute("channel", "Unknown channel.")
    if channel != "email":
        raise InvalidRoute("channel", "Only the email channel takes a routed destination.")
    addresses = target.get("addresses") if isinstance(target, dict) else None
    if not isinstance(addresses, list) or not 1 <= len(addresses) <= MAX_ADDRESSES:
        raise InvalidRoute("target", f"Send 1 to {MAX_ADDRESSES} addresses.")
    clean = []
    for address in addresses:
        try:
            validate_email(address)
        except ValidationError:
            raise InvalidRoute("target", "One of the addresses is not valid.") from None
        clean.append(address.strip().lower())
    return {"addresses": sorted(set(clean))}


def target_hash(target: dict) -> str:
    return hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()


@transaction.atomic
def save_route(*, actor, purpose_code, channel, target, is_active=True, route=None):
    purpose = purpose_of(purpose_code)
    if "broadcast" not in purpose.audience:
        raise InvalidRoute("purpose_code", "This purpose is not a broadcast purpose.")
    target = validate_target(channel, target)
    route = route or NotificationRoute(created_by=actor)
    old = {"target": route.target, "is_active": route.is_active} if route.pk else None
    route.purpose_code, route.channel, route.target = purpose_code, channel, target
    route.target_hash, route.is_active, route.updated_by = target_hash(target), is_active, actor
    try:
        with transaction.atomic():
            route.save()
    except IntegrityError:
        raise InvalidRoute("target", "This route already exists.") from None
    audit.record(
        "core.notification_route.saved",
        route,
        actor=actor,
        meta={"purpose": purpose_code, "channel": channel, "was": old},  # a re-point redirects data
    )
    return route


@transaction.atomic
def delete_route(*, actor, route):
    audit.record(
        "core.notification_route.deleted",
        route,
        actor=actor,
        meta={"purpose": route.purpose_code, "channel": route.channel},
    )
    route.delete()


def matrix() -> list[dict]:
    cells = {(c.purpose_code, c.channel): c.enabled for c in NotificationSetting.objects.all()}
    states = {s.purpose_code: s.test_routing for s in NotificationPurposeState.objects.all()}
    out = []
    for purpose in registry.notification_purposes.purposes():
        out.append(
            {
                "purpose": purpose.code,
                "label": purpose.label,
                "module": purpose.owner_module,
                "mandatory": purpose.mandatory,
                "carries_token": purpose.carries_token,
                "test_routing": states.get(purpose.code, purpose.rollout),
                "channels": {
                    c.key: {
                        "enabled": True
                        if purpose.mandatory and c.key in purpose.default_channels
                        else cells.get((purpose.code, c.key), c.key in purpose.default_channels),
                        "locked": purpose.mandatory,
                    }
                    for c in registry.notification_channels.channels()
                },
            }
        )
    return out


@transaction.atomic
def set_cells(*, actor, changes: list[dict]) -> None:
    """Each change: {purpose, channel, enabled} or {purpose, test_routing}. Audited old -> new."""
    for change in changes:
        purpose = purpose_of(change.get("purpose", ""))
        if "channel" in change:
            if change["channel"] not in registry.notification_channels:
                raise InvalidRoute("channel", "Unknown channel.")
            if purpose.mandatory:
                raise Locked("A security notice cannot be switched off.")
            old = engine.matrix_enabled(purpose, change["channel"])
            NotificationSetting.objects.update_or_create(
                purpose_code=purpose.code,
                channel=change["channel"],
                defaults={"enabled": bool(change["enabled"]), "updated_by": actor},
            )
            audit.record(
                "core.notification_matrix.changed",
                actor=actor,
                meta={
                    "purpose": purpose.code,
                    "channel": change["channel"],
                    "old": old,
                    "new": bool(change["enabled"]),
                },
            )
        elif "test_routing" in change:
            wanted = bool(change["test_routing"])
            if wanted and purpose.carries_token and engine.is_production():
                raise Locked("A token-bearing purpose is never test-routed in production.")
            old = NotificationPurposeState.objects.filter(purpose_code=purpose.code).first()
            NotificationPurposeState.objects.update_or_create(
                purpose_code=purpose.code, defaults={"test_routing": wanted, "updated_by": actor}
            )
            audit.record(
                "core.notification_matrix.changed",
                actor=actor,
                meta={
                    "purpose": purpose.code,
                    "test_routing_old": old.test_routing if old else purpose.rollout,
                    "test_routing_new": wanted,
                },
            )


def preferences_for(user) -> list[dict]:
    out = []
    for purpose in registry.notification_purposes.purposes():
        if "user" not in purpose.audience:
            continue
        out.append(
            {
                "purpose": purpose.code,
                "label": purpose.label,
                "module": purpose.owner_module,
                "mandatory": purpose.mandatory,
                "channels": {
                    c.key: engine.preference_enabled(user.pk, purpose, c.key)
                    for c in registry.notification_channels.channels()
                    if c.key in purpose.default_channels
                    or NotificationSetting.objects.filter(
                        purpose_code=purpose.code, channel=c.key, enabled=True
                    ).exists()
                },
            }
        )
    return out


@transaction.atomic
def set_preferences(*, user, changes: list[dict]) -> None:
    """Each change: {purpose, channel, enabled}. A mandatory purpose cannot be opted out of."""
    for change in changes:
        purpose = purpose_of(change.get("purpose", ""))
        if change.get("channel") not in registry.notification_channels:
            raise InvalidRoute("channel", "Unknown channel.")
        if purpose.mandatory:
            raise Locked("A security notice cannot be switched off.")
        NotificationPreference.objects.update_or_create(
            user=user,
            purpose_code=purpose.code,
            channel=change["channel"],
            defaults={"enabled": bool(change["enabled"])},
        )


def send_test(*, actor, purpose_code: str, channel: str | None = None, route=None) -> list[dict]:
    purpose = purpose_of(purpose_code)
    results = engine.send_test(purpose, actor=actor, channel=channel, route=route)
    audit.record(
        "core.notification.test_sent",
        route,
        actor=actor,
        meta={"purpose": purpose_code, "results": [r["status"] for r in results]},
    )
    return results


def deliveries(limit: int = 100):
    return NotificationDelivery.objects.select_related("recipient").order_by("-id")[:limit]
