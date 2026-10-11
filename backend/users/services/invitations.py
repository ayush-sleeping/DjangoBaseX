"""
Invitations: the only route to a new account by default (AUTH_BLUEPRINT § 3.5, A25).

The invited role is assigned by rbac, on the `invitation_accepted` signal: users references
rbac.Role by string only and never imports rbac (Ch. 2).
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from core.audit import log_activity

from .. import emails, signals, tokens
from ..models import Invitation, User
from ..models.user import normalize_email

logger = logging.getLogger(__name__)


class InvitationError(Exception):
    code = "invalid"


class AlreadyInvited(InvitationError):
    code = "already_invited"


class AlreadyAUser(InvitationError):
    code = "already_a_user"


class ElevatedRequiresSuperuser(InvitationError):
    """Inviting someone into an elevated role is granting it: superusers only (§ 8.2)."""

    code = "elevated_requires_superuser"


class NotPending(InvitationError):
    code = "not_pending"


class InvalidInvitationToken(InvitationError):
    """Unknown, used, revoked or expired. Callers answer all four identically."""

    code = "invalid_token"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@transaction.atomic
def invite(*, actor, email: str, role) -> Invitation:
    email = normalize_email(email)
    if role.is_elevated and (actor is None or not actor.is_superuser):
        raise ElevatedRequiresSuperuser
    if User.objects.filter(email=email).exists():
        raise AlreadyAUser
    now = timezone.now()
    live = Invitation.objects.live().select_for_update().filter(email=email).first()
    if live is not None:
        if live.expires_at > now:
            raise AlreadyInvited
        live.revoked_at = now  # an expired invite must not block a fresh one forever
        live.save(update_fields=["revoked_at"])
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        email=email,
        role=role,
        token_hash=_hash(raw_token),
        invited_by=actor,
        expires_at=now + timedelta(seconds=settings.INVITATION_LIFETIME),
    )
    transaction.on_commit(lambda: _send(invitation, raw_token))
    log_activity("users.invitation.sent", actor=actor, target=invitation, role=role.slug)
    return invitation


def _send(invitation, raw_token: str) -> None:
    try:
        emails.send_invitation(invitation, raw_token)
    except Exception:  # noqa: BLE001 — the row exists; it can be revoked and re-sent
        logger.exception("invitation email %s failed", invitation.public_id)


@transaction.atomic
def revoke(*, actor, invitation: Invitation) -> Invitation:
    if invitation.status != "pending":
        raise NotPending
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at"])
    log_activity("users.invitation.revoked", actor=actor, target=invitation)
    return invitation


def accept(request, raw_token: str, password: str, full_name: str = "") -> tokens.IssuedTokens:
    """
    Create the account, assign the invited role, and sign the person in. Raises
    InvalidInvitationToken, or Django's ValidationError for a refused password (the link is then
    still usable).
    """
    with transaction.atomic():
        invitation = (
            # of=("self",): invited_by is nullable, so it is an outer join, and PostgreSQL refuses
            # FOR UPDATE on the nullable side of one (SQLite ignores the lock, so only CI saw it).
            Invitation.objects.select_for_update(of=("self",))
            .select_related("invited_by")
            .filter(token_hash=_hash(raw_token or ""))
            .first()
        )
        if invitation is None or invitation.status != "pending":
            raise InvalidInvitationToken
        if User.objects.filter(email=invitation.email).exists():
            raise InvalidInvitationToken  # someone created the account another way meanwhile
        validate_password(password, user=User(email=invitation.email, full_name=full_name))
        user = User.objects.create_user(
            invitation.email, password, full_name=full_name[:255], is_active=True
        )
        invitation.accepted_at = timezone.now()
        invitation.accepted_user = user
        invitation.save(update_fields=["accepted_at", "accepted_user"])
        signals.invitation_accepted.send(
            sender=Invitation,
            user=user,
            role_id=invitation.role_id,
            invited_by=invitation.invited_by,
        )
        issued = tokens.issue_pair(user, request)
    log_activity("users.invitation.accepted", actor=user, target=invitation)
    return issued
