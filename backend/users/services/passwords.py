"""Password reset and the password-change cascade (AUTH_BLUEPRINT § 6.6–6.7, Ch. 18)."""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from core.audit import log_activity
from core.http import client_ip

from .. import emails, tokens
from ..models import PasswordResetToken, User, UserSession
from ..models.user import normalize_email

logger = logging.getLogger(__name__)


class InvalidResetToken(Exception):
    """Unknown, used, expired, or for an inactive account. Callers answer all four identically."""


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def request_reset(request, email: str) -> None:
    """
    Always returns normally, whether or not the address exists: the endpoint answers 204 either
    way (§ 6.6). Only an existing, active account gets a token and an email.
    """
    user = User.objects.filter(email=normalize_email(email or ""), is_active=True).first()
    if user is None:
        return
    raw_token = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        token_hash=_hash(raw_token),
        expires_at=timezone.now() + timedelta(seconds=settings.PASSWORD_RESET_TOKEN_LIFETIME),
        requested_ip=client_ip(request),
    )
    # After the commit (Ch. 18 rule 1), and a delivery failure never reaches the response (rule 2).
    transaction.on_commit(lambda: _send_reset_email(user, raw_token))
    log_activity("auth.password_reset_requested", actor=user, ip=client_ip(request))


def _send_reset_email(user, raw_token: str) -> None:
    try:
        emails.send_password_reset(user, raw_token)
    except Exception:  # noqa: BLE001 — any failure here must not become an enumeration oracle
        logger.exception("password reset email to user %s failed", user.public_id)


def perform_reset(request, raw_token: str, new_password: str) -> User:
    """
    Set a new password from a valid token. Raises InvalidResetToken, or Django's ValidationError
    when the password fails the validators (the token is then still usable).
    """
    with transaction.atomic():
        token = (
            PasswordResetToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=_hash(raw_token or ""))
            .first()
        )
        now = timezone.now()
        if (
            token is None
            or token.used_at is not None
            or token.expires_at <= now
            or not token.user.is_active
        ):
            raise InvalidResetToken
        user = token.user
        validate_password(new_password, user=user)
        token.used_at = now
        token.save(update_fields=["used_at"])
        user.set_password(new_password)
        user.save()  # sends password_changed: the cascade below runs
    log_activity("auth.password_reset", actor=user, ip=client_ip(request))
    return user


def on_password_changed(sender, user, **kwargs) -> None:
    """§ 6.7: every session ends, the current one included, and every outstanding link dies."""
    tokens.revoke_all_for_user(user, UserSession.RevokedReason.PASSWORD_CHANGED)
    PasswordResetToken.objects.outstanding().filter(user=user).update(expires_at=timezone.now())
    log_activity("auth.password_changed", actor=user)
