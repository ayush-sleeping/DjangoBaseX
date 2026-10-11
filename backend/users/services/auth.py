"""Login, refresh and logout (AUTH_BLUEPRINT § 6.2–6.5). Views call these and only these."""

from dataclasses import dataclass

from django.contrib.auth import authenticate, user_logged_in
from django.utils import timezone

from core.audit import log_activity
from core.http import client_ip

from .. import tokens
from ..models import LoginAttempt, User, UserSession
from ..models.user import normalize_email
from . import lockout
from .mfa import has_confirmed_device


class InvalidCredentials(Exception):
    """Wrong password, unknown address or inactive account: callers answer all three identically."""


LockedOut = lockout.LockedOut


@dataclass(frozen=True)
class MfaChallenge:
    """The password was right and a confirmed device exists: the caller must now ask for a code."""

    mfa_token: str


def login(request, email: str, password: str) -> tokens.IssuedTokens | MfaChallenge:
    identifier = normalize_email(email or "")
    ip = client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]

    # Step 2. Checked before the password, so a locked account cannot be probed. The answer is the
    # same for addresses that exist and those that do not: locks are keyed on what was typed.
    if lockout.is_locked(identifier, ip):
        _record(identifier, None, ip, user_agent, LoginAttempt.FailureReason.LOCKED)
        raise LockedOut

    # The backend runs the password hasher even for an unknown address (timing parity), and it is
    # AllowAllUsersModelBackend, so an inactive user comes back here and step 5 can record why.
    user = authenticate(request, email=identifier, password=password)

    if user is None:
        known = User.objects.filter(email=identifier).first()
        reason = (
            LoginAttempt.FailureReason.BAD_PASSWORD
            if known
            else LoginAttempt.FailureReason.UNKNOWN_USER
        )
        _record(identifier, known, ip, user_agent, reason)
        raise InvalidCredentials
    if not user.is_active:
        _record(identifier, user, ip, user_agent, LoginAttempt.FailureReason.INACTIVE)
        raise InvalidCredentials

    # Step 6. Nothing is recorded yet: the attempt succeeds or fails at the code (services.mfa).
    if has_confirmed_device(user):
        return MfaChallenge(mfa_token=tokens.issue_mfa_token(user))

    issued = tokens.issue_pair(user, request)
    _record(identifier, user, ip, user_agent, reason="")
    user_logged_in.send(sender=user.__class__, request=request, user=user)  # sets last_login
    log_activity("auth.login", actor=user, ip=ip, user_agent=user_agent)
    return issued


def refresh(request, refresh_token: str) -> tokens.IssuedTokens:
    """Raises tokens.TokenError for every refusal; the view answers 401 and clears cookies."""
    try:
        return tokens.rotate(refresh_token, request)
    except tokens.ReuseDetected:
        log_activity("auth.token_reuse_detected", ip=client_ip(request))
        raise


def logout(request) -> None:
    session = UserSession.objects.filter(public_id=request.auth["sid"]).first()
    if session is not None:
        tokens.revoke(session, UserSession.RevokedReason.LOGOUT)
    log_activity("auth.logout", actor=request.user, ip=client_ip(request))


def revoke_other_sessions(request) -> int:
    """'Sign out everywhere else': every live session of this user except the current one."""
    count = tokens.revoke_all_for_user(
        request.user, UserSession.RevokedReason.LOGOUT, keep_sid=request.auth["sid"]
    )
    log_activity("auth.sessions_revoked", actor=request.user, count=count)
    return count


def confirm_password(request, password: str) -> None:
    """§ 6.9: stamp THIS session as recently re-authenticated. Raises InvalidCredentials."""
    if not request.user.check_password(password):
        log_activity("auth.password_confirm_failed", actor=request.user, ip=client_ip(request))
        raise InvalidCredentials
    UserSession.objects.filter(public_id=request.auth["sid"]).update(
        password_confirmed_at=timezone.now()
    )
    log_activity("auth.password_confirmed", actor=request.user, ip=client_ip(request))


def _record(identifier, user, ip, user_agent, reason) -> None:
    LoginAttempt.objects.create(
        identifier=identifier,
        user=user,
        ip=ip,
        user_agent=user_agent,
        succeeded=not reason,
        failure_reason=reason,
    )
