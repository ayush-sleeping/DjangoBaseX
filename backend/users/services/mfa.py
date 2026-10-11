"""TOTP enrolment, verification at login, and disabling (AUTH_BLUEPRINT § 6.8)."""

from django.contrib.auth import user_logged_in
from django.db import transaction
from django.utils import timezone

from core.audit import log_activity
from core.http import client_ip

from .. import mfa, tokens
from ..models import LoginAttempt, MfaDevice, MfaRecoveryCode, User
from . import lockout

RECOVERY_CODE_COUNT = 10


class AlreadyEnabled(Exception):
    """setup/ while a confirmed device exists."""


class InvalidCode(Exception):
    """A TOTP or recovery code that does not verify (wrong, replayed, or no device)."""


class InvalidMfaToken(Exception):
    """The mfa_token is expired, used or forged, or its account can no longer sign in."""


def has_confirmed_device(user) -> bool:
    return MfaDevice.objects.confirmed().filter(user=user).exists()


# --- Enrolment ----------------------------------------------------------------------------------


def begin_setup(user, label: str = "") -> dict:
    """A new unconfirmed device, replacing any earlier unconfirmed one."""
    if has_confirmed_device(user):
        raise AlreadyEnabled
    secret = mfa.new_secret()  # raises nothing; encryption below fails loudly if no key is set
    with transaction.atomic():
        MfaDevice.objects.filter(user=user, confirmed_at__isnull=True).delete()
        MfaDevice.objects.create(user=user, label=label[:64], secret=mfa.encrypt_secret(secret))
    log_activity("auth.mfa_setup_started", actor=user)
    return {"otpauth_uri": mfa.provisioning_uri(secret, user.email), "secret": secret}


def confirm_setup(user, code: str) -> list[str]:
    """Verify the first code from the pending device, enrol it, and issue fresh recovery codes."""
    with transaction.atomic():
        device = (
            MfaDevice.objects.select_for_update()
            .filter(user=user, confirmed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if device is None:
            raise InvalidCode
        step = mfa.verify_totp(mfa.decrypt_secret(device.secret), code, device.last_used_timestep)
        if step is None:
            raise InvalidCode
        now = timezone.now()
        device.confirmed_at = now
        device.last_used_at = now
        device.last_used_timestep = step
        device.save(update_fields=["confirmed_at", "last_used_at", "last_used_timestep"])
        codes = mfa.generate_recovery_codes(RECOVERY_CODE_COUNT)
        MfaRecoveryCode.objects.filter(user=user).delete()
        MfaRecoveryCode.objects.bulk_create(
            MfaRecoveryCode(user=user, code_hash=mfa.hash_recovery_code(c)) for c in codes
        )
    log_activity("auth.mfa_enabled", actor=user)
    return codes


def disable(user) -> None:
    """What an attacker does after a takeover: gated by re-auth, loud in the audit log."""
    with transaction.atomic():
        MfaDevice.objects.filter(user=user).delete()
        MfaRecoveryCode.objects.filter(user=user).delete()
    log_activity("auth.mfa_disabled", actor=user)


# --- The login's second step --------------------------------------------------------------------


def verify_login(request, mfa_token: str, code: str) -> tokens.IssuedTokens:
    """
    Exchange the password step's mfa_token and a TOTP or recovery code for a real session.
    Failures are LoginAttempt(mfa_failed) and count toward the same lockout as passwords.
    """
    try:
        claims = tokens.read_mfa_token(mfa_token)
    except tokens.TokenError as exc:
        raise InvalidMfaToken from exc
    user = User.objects.filter(public_id=claims["sub"]).first()
    if user is None or not user.is_active:
        raise InvalidMfaToken

    ip = client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]
    if lockout.is_locked(user.email, ip):
        _record(user, ip, user_agent, LoginAttempt.FailureReason.LOCKED)
        raise lockout.LockedOut

    if not (_accept_totp(user, code) or _accept_recovery_code(user, code)):
        _record(user, ip, user_agent, LoginAttempt.FailureReason.MFA_FAILED)
        raise InvalidCode
    if not tokens.burn_mfa_token(claims):
        raise InvalidMfaToken  # a concurrent verify with the same token won the race

    issued = tokens.issue_pair(user, request)
    _record(user, ip, user_agent, reason="")
    user_logged_in.send(sender=user.__class__, request=request, user=user)
    log_activity("auth.login", actor=user, ip=ip, user_agent=user_agent, mfa=True)
    return issued


def _accept_totp(user, code: str) -> bool:
    with transaction.atomic():
        for device in MfaDevice.objects.confirmed().select_for_update().filter(user=user):
            step = mfa.verify_totp(
                mfa.decrypt_secret(device.secret), code, device.last_used_timestep
            )
            if step is not None:
                device.last_used_timestep = step  # monotonic: this code can never be replayed
                device.last_used_at = timezone.now()
                device.save(update_fields=["last_used_timestep", "last_used_at"])
                return True
    return False


def _accept_recovery_code(user, code: str) -> bool:
    used = (
        MfaRecoveryCode.objects.filter(
            user=user, code_hash=mfa.hash_recovery_code(code), used_at__isnull=True
        ).update(used_at=timezone.now())
        == 1
    )
    if used:
        log_activity("auth.mfa_recovery_code_used", actor=user)
    return used


def _record(user, ip, user_agent, reason) -> None:
    LoginAttempt.objects.create(
        identifier=user.email,
        user=user,
        ip=ip,
        user_agent=user_agent,
        succeeded=not reason,
        failure_reason=reason,
    )
