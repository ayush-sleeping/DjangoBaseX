"""
Managing other people's accounts (AUTH_BLUEPRINT § 8.3, § 8.5, § 10.2). The reference shape for a
module's services: keyword `actor`, one transaction, an audit row, and guards here, not in views.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.audit import log_activity

from .. import emails, tokens
from ..models import PasswordResetToken, User, UserSession
from ..models.user import normalize_email

logger = logging.getLogger(__name__)


class UsersError(Exception):
    code = "invalid"


class SelfDeactivation(UsersError):
    """Deactivating yourself locks you out with no way back in."""

    code = "self_deactivation"


class LastSuperuser(UsersError):
    """A system with no active superuser cannot grant anyone the right to fix it (§ 8.3)."""

    code = "last_superuser"


@transaction.atomic
def create_user(*, actor, email: str, full_name: str = "") -> User:
    """
    An active account with no usable password. The person sets one through an emailed link: an
    operator never chooses, sees or sends someone else's password.
    """
    user = User.objects.create_user(normalize_email(email), password=None, full_name=full_name)
    user.is_active = True
    user.save(update_fields=["is_active"])
    raw_token = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(seconds=settings.PASSWORD_SETUP_TOKEN_LIFETIME),
    )
    transaction.on_commit(lambda: _send_setup(user, raw_token))
    log_activity("users.user.created", actor=actor, target=user)
    return user


def _send_setup(user, raw_token: str) -> None:
    try:
        emails.send_account_setup(user, raw_token)
    except Exception:  # noqa: BLE001 — the account exists; the operator can resend via forgot
        logger.exception("account setup email to user %s failed", user.public_id)


@transaction.atomic
def update_user(*, actor, user: User, full_name: str) -> User:
    user.full_name = full_name
    user.save(update_fields=["full_name", "updated_at"])
    log_activity("users.user.updated", actor=actor, target=user, fields=["full_name"])
    return user


@transaction.atomic
def deactivate(*, actor, user: User, reason: str = "") -> User:
    if actor is not None and actor.pk == user.pk:
        raise SelfDeactivation
    if (
        user.is_superuser
        and user.is_active
        and not User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk).exists()
    ):
        raise LastSuperuser
    user.is_active = False
    user.deactivated_at = timezone.now()
    user.deactivated_reason = reason[:255]
    user.save(update_fields=["is_active", "deactivated_at", "deactivated_reason", "updated_at"])
    # § 8.5: access already stops (the authenticator checks is_active), but the session RECORD
    # must say so too — it is what an incident is reconstructed from.
    tokens.revoke_all_for_user(user, UserSession.RevokedReason.ADMIN)
    log_activity("users.user.deactivated", actor=actor, target=user, reason=reason)
    return user


@transaction.atomic
def activate(*, actor, user: User) -> User:
    user.is_active = True
    user.deactivated_at = None
    user.deactivated_reason = ""
    user.save(update_fields=["is_active", "deactivated_at", "deactivated_reason", "updated_at"])
    log_activity("users.user.activated", actor=actor, target=user)
    return user


@transaction.atomic
def revoke_sessions(*, actor, user: User) -> int:
    count = tokens.revoke_all_for_user(user, UserSession.RevokedReason.ADMIN)
    log_activity("users.sessions.revoked", actor=actor, target=user, count=count)
    return count
