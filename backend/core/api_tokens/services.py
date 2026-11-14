"""
The ONE issuing path for machine credentials (API_PLATFORM.md § 8): the API, and any future CLI,
call issue_token(); nothing else creates an ApiToken. Every write is audited, naming the consumer.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core import audit
from core.registry import registry

from .models import ApiConsumer, ApiToken

MAX_LIFETIME_DAYS = 365
ROTATION_OVERLAP_HOURS = 24
WILDCARD = "*"


class TokenError(Exception):
    """A refused issue/rotate/scope change. `field` names the offending input."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def token_prefix() -> str:
    """Derived from the project slug, so a secret scanner can learn to recognise a leak."""
    return settings.PRODUCT_SLUG


def digest_of(plaintext: str) -> str:
    # A random 256-bit token needs no slow hash, and it is checked on every request.
    return hashlib.sha256(plaintext.encode()).hexdigest()


def role_grants(role_id: int) -> frozenset[str]:
    """The service role's live, non-deprecated permission codes (gate 2 of ADR-0016)."""
    from django.apps import apps

    RolePermission = apps.get_model("rbac", "RolePermission")  # noqa: N806 — core never imports rbac
    return frozenset(
        RolePermission.objects.filter(role_id=role_id, permission__is_deprecated=False).values_list(
            "permission__code", flat=True
        )
    )


def scope_allows(scopes, code: str) -> bool:
    return WILDCARD in scopes or code in scopes


def validate_scopes(scopes, role_id: int) -> list[str]:
    if not isinstance(scopes, list) or not scopes or not all(isinstance(s, str) for s in scopes):
        raise TokenError("scopes", "Give a non-empty list of permission codes.")
    scopes = list(dict.fromkeys(scopes))
    if WILDCARD in scopes:
        if scopes != [WILDCARD]:
            raise TokenError("scopes", '"*" cannot be combined with other scopes.')
        return scopes
    catalogue = registry.permissions.codes()
    unknown = [s for s in scopes if s not in catalogue]
    if unknown:
        raise TokenError("scopes", f"Unknown permission code: {', '.join(sorted(unknown))}.")
    ungranted = sorted(set(scopes) - role_grants(role_id))
    if ungranted:
        raise TokenError("scopes", f"The service role does not grant: {', '.join(ungranted)}.")
    return scopes


def _validate_expiry(expires_at: datetime | None) -> datetime:
    now = timezone.now()
    if expires_at is None:
        raise TokenError("expires_at", "An expiry is required.")
    if expires_at <= now:
        raise TokenError("expires_at", "The expiry must be in the future.")
    if expires_at > now + timedelta(days=MAX_LIFETIME_DAYS):
        raise TokenError("expires_at", f"A token lives at most {MAX_LIFETIME_DAYS} days.")
    return expires_at


def _mint(*, actor, consumer, name, scopes, expires_at, rotated_from=None):
    plaintext = f"{token_prefix()}_{secrets.token_urlsafe(32)}"
    shown = plaintext[len(token_prefix()) + 1 :][:6]
    token = ApiToken.objects.create(
        consumer=consumer,
        name=name,
        prefix=f"{token_prefix()}_{shown}",
        digest=digest_of(plaintext),
        scopes=scopes,
        expires_at=expires_at,
        created_by=actor,
        rotated_from=rotated_from,
    )
    return token, plaintext


@transaction.atomic
def issue_token(*, actor, consumer: ApiConsumer, name: str, scopes, expires_at):
    """Returns (token, plaintext). The plaintext is never available again."""
    if not consumer.is_active:
        raise TokenError("consumer", "The consumer is deactivated.")
    scopes = validate_scopes(scopes, consumer.service_role_id)
    expires_at = _validate_expiry(expires_at)
    token, plaintext = _mint(
        actor=actor, consumer=consumer, name=name, scopes=scopes, expires_at=expires_at
    )
    audit.record(
        "core.api_token.issued",
        token,
        actor=actor,
        meta={"consumer": consumer.name, "scopes": scopes, "expires_at": expires_at.isoformat()},
    )
    return token, plaintext


@transaction.atomic
def rotate_token(*, actor, token: ApiToken):
    """Mint a successor with the same scopes, and let the predecessor die after the overlap."""
    if token.revoked_at is not None:
        raise TokenError("token", "A revoked token cannot be rotated.")
    consumer = token.consumer
    now = timezone.now()
    scopes = validate_scopes(token.scopes, consumer.service_role_id)
    expires_at = min(token.expires_at, now + timedelta(days=MAX_LIFETIME_DAYS))
    successor, plaintext = _mint(
        actor=actor,
        consumer=consumer,
        name=token.name,
        scopes=scopes,
        expires_at=max(expires_at, now + timedelta(hours=ROTATION_OVERLAP_HOURS)),
        rotated_from=token,
    )
    overlap_end = now + timedelta(hours=ROTATION_OVERLAP_HOURS)
    if token.expires_at > overlap_end:
        token.expires_at = overlap_end
        token.save(update_fields=["expires_at"])
    audit.record(
        "core.api_token.rotated",
        successor,
        actor=actor,
        meta={"consumer": consumer.name, "predecessor": str(token.public_id)},
    )
    return successor, plaintext


@transaction.atomic
def set_scopes(*, actor, token: ApiToken, scopes) -> ApiToken:
    scopes = validate_scopes(scopes, token.consumer.service_role_id)
    before = token.scopes
    token.scopes = scopes
    token.save(update_fields=["scopes"])
    audit.record(
        "core.api_token.scopes_changed",
        token,
        actor=actor,
        meta={"consumer": token.consumer.name, "before": before, "after": scopes},
    )
    return token


@transaction.atomic
def revoke_token(*, actor, token: ApiToken, reason: str = "") -> ApiToken:
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.revoked_by = actor
        token.revoked_reason = reason[:255]
        token.save(update_fields=["revoked_at", "revoked_by", "revoked_reason"])
        audit.record(
            "core.api_token.revoked",
            token,
            actor=actor,
            meta={"consumer": token.consumer.name, "reason": reason[:255]},
        )
    return token


@transaction.atomic
def create_consumer(*, actor, **fields) -> ApiConsumer:
    consumer = ApiConsumer.objects.create(created_by=actor, **fields)
    audit.record(
        "core.api_consumer.created",
        consumer,
        actor=actor,
        meta={"service_role": consumer.service_role.slug},
    )
    return consumer


@transaction.atomic
def update_consumer(*, actor, consumer: ApiConsumer, **fields) -> ApiConsumer:
    """Describe a consumer and (de)activate it; deactivation is the audited kill switch."""
    was_active = consumer.is_active
    reason = fields.pop("disabled_reason", None)
    for key, value in fields.items():
        setattr(consumer, key, value)
    if "is_active" in fields and fields["is_active"] != was_active:
        consumer.disabled_at = None if consumer.is_active else timezone.now()
        consumer.disabled_reason = "" if consumer.is_active else (reason or "")[:255]
    consumer.save()
    if consumer.is_active != was_active:
        audit.record(
            "core.api_consumer.activated"
            if consumer.is_active
            else "core.api_consumer.deactivated",
            consumer,
            actor=actor,
            meta={"reason": consumer.disabled_reason},
        )
    else:
        audit.record(
            "core.api_consumer.updated", consumer, actor=actor, meta={"fields": list(fields)}
        )
    return consumer
