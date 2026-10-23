"""
MFA and re-auth through the real endpoints (AUTH_BLUEPRINT § 6.8–6.9, BUILD_ORDER 1.1d).
TOTP codes are computed with pyotp from the secret setup/ returns.
"""

from datetime import timedelta

import pyotp
import pytest
from django.test import Client
from django.utils import timezone

from tests.factories import DEFAULT_PASSWORD, UserFactory
from users.cookies import cookie_names
from users.models import LoginAttempt, MfaDevice, UserSession

pytestmark = pytest.mark.django_db

NAMES = cookie_names()
LOGIN, ME = "/api/auth/login/", "/api/auth/me/"
SETUP, CONFIRM = "/api/auth/mfa/setup/", "/api/auth/mfa/confirm/"
VERIFY, DISABLE = "/api/auth/mfa/verify/", "/api/auth/mfa/disable/"
PASSWORD_CONFIRM, REVOKE_ALL = "/api/auth/password/confirm/", "/api/auth/sessions/revoke-all/"


def post(client, path, data=None, **extra):
    csrf = client.cookies.get(NAMES.csrf)
    if csrf is not None and csrf.value:
        extra.setdefault("HTTP_X_CSRF_TOKEN", csrf.value)
    return client.post(path, data or {}, content_type="application/json", **extra)


def sign_in(client, user):
    return post(client, LOGIN, {"email": user.email, "password": DEFAULT_PASSWORD})


def code_at(secret: str, offset_steps: int = 0) -> str:
    return pyotp.TOTP(secret).at(timezone.now() + timedelta(seconds=30 * offset_steps))


def enrol(client, user) -> tuple[str, list[str]]:
    """Sign in, set up and confirm a device. Returns (secret, recovery codes)."""
    assert sign_in(client, user).status_code == 204
    setup = post(client, SETUP)
    assert setup.status_code == 200, setup.content
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    confirm = post(client, CONFIRM, {"code": code_at(secret)})
    assert confirm.status_code == 200, confirm.content
    return secret, confirm.json()["recovery_codes"]


def mfa_token(user) -> str:
    response = sign_in(Client(), user)
    assert response.status_code == 200
    assert response.json()["mfa_required"] is True
    assert NAMES.access not in response.cookies  # no session before the code
    return response.json()["mfa_token"]


# --- Enrolment ----------------------------------------------------------------------------------


def test_enrolment_issues_ten_recovery_codes_and_shows_on_me(client):
    user = UserFactory()
    _, codes = enrol(client, user)

    assert len(codes) == 10 and len(set(codes)) == 10
    assert client.get(ME).json()["mfa_enabled"] is True
    assert MfaDevice.objects.get(user=user).confirmed_at is not None


def test_the_secret_is_stored_encrypted_not_as_base32(client):
    user = UserFactory()
    secret, _ = enrol(client, user)
    assert secret.encode() not in bytes(MfaDevice.objects.get(user=user).secret)


def test_setup_is_refused_once_mfa_is_on(client):
    enrol(client, UserFactory())
    assert post(client, SETUP).json()["error"]["code"] == "mfa_already_enabled"


def test_an_unconfirmed_device_does_not_trigger_the_code_step(client):
    user = UserFactory()
    sign_in(client, user)
    post(client, SETUP)  # never confirmed
    assert sign_in(Client(), user).status_code == 204


def test_setup_without_an_encryption_key_answers_503(client, settings):
    settings.MFA_ENCRYPTION_KEY = ""
    sign_in(client, UserFactory())
    response = post(client, SETUP)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "mfa_unavailable"


# --- The login code step ------------------------------------------------------------------------


def test_sign_in_with_mfa_needs_the_code_and_the_token_works_once(client):
    user = UserFactory()
    secret, _ = enrol(client, user)
    token = mfa_token(user)

    browser = Client()
    verified = post(browser, VERIFY, {"mfa_token": token, "code": code_at(secret, +1)})
    assert verified.status_code == 204
    assert browser.get(ME).status_code == 200

    reused = post(Client(), VERIFY, {"mfa_token": token, "code": code_at(secret, +1)})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "mfa_token_invalid"


def test_a_totp_code_cannot_be_replayed(client):
    user = UserFactory()
    secret, _ = enrol(client, user)
    code = code_at(secret, +1)
    assert post(Client(), VERIFY, {"mfa_token": mfa_token(user), "code": code}).status_code == 204

    replay = post(Client(), VERIFY, {"mfa_token": mfa_token(user), "code": code})
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "invalid_mfa_code"


def test_a_recovery_code_works_once(client):
    user = UserFactory()
    _, codes = enrol(client, user)
    spaced = codes[0].lower().replace("-", " ")  # normalised before hashing

    assert post(Client(), VERIFY, {"mfa_token": mfa_token(user), "code": spaced}).status_code == 204
    again = post(Client(), VERIFY, {"mfa_token": mfa_token(user), "code": codes[0]})
    assert again.status_code == 400


def test_a_wrong_code_is_recorded_and_counts_toward_lockout(client):
    user = UserFactory()
    enrol(client, user)
    wrong = post(Client(), VERIFY, {"mfa_token": mfa_token(user), "code": "000000"})
    assert wrong.status_code == 400
    assert LoginAttempt.objects.filter(failure_reason="mfa_failed").count() == 1

    token = mfa_token(user)  # obtained before the lock
    for _ in range(10):
        LoginAttempt.objects.create(
            identifier=user.email, succeeded=False, failure_reason="mfa_failed"
        )
    # One lockout for passwords and codes alike: both steps now refuse.
    assert post(Client(), VERIFY, {"mfa_token": token, "code": "000000"}).status_code == 429
    assert sign_in(Client(), user).status_code == 429


def test_an_expired_mfa_token_is_refused(client, settings):
    user = UserFactory()
    secret, _ = enrol(client, user)
    settings.MFA_TOKEN_LIFETIME = -1
    expired = post(Client(), VERIFY, {"mfa_token": mfa_token(user), "code": code_at(secret, +1)})
    assert expired.status_code == 401


def test_an_mfa_token_is_not_an_access_token(client):
    user = UserFactory()
    enrol(client, user)
    browser = Client()
    browser.cookies[NAMES.access] = mfa_token(user)
    assert browser.get(ME).status_code == 401


# --- Enrolment gate -----------------------------------------------------------------------------


def test_an_enforced_user_without_a_device_can_only_enrol(client):
    user = UserFactory(mfa_enforced=True)
    assert sign_in(client, user).status_code == 204

    blocked = post(client, REVOKE_ALL)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "mfa_enrollment_required"
    assert client.get(ME).status_code == 200  # exempt, so the frontend can route
    assert post(client, SETUP).status_code == 200  # exempt, or they could never fix it


def test_an_enforced_user_with_a_device_is_not_gated(client):
    user = UserFactory(mfa_enforced=True)
    secret, _ = enrol(client, user)
    browser = Client()
    post(browser, VERIFY, {"mfa_token": mfa_token(user), "code": code_at(secret, +1)})
    assert post(browser, REVOKE_ALL).status_code == 200


# --- Re-auth and disabling ----------------------------------------------------------------------


def test_disable_needs_no_reauth_until_an_operator_opts_in(client):
    enrol(client, UserFactory())
    assert post(client, DISABLE).status_code == 204
    assert client.get(ME).json()["mfa_enabled"] is False


def test_disable_with_reauth_on_answers_423_until_the_password_is_confirmed(
    client, setting_override
):
    setting_override("security.reauth.actions", ["mfa_disable"])
    user = UserFactory()
    enrol(client, user)

    refused = post(client, DISABLE)
    assert refused.status_code == 423
    assert refused.json()["error"]["code"] == "reauth_required"

    assert post(client, PASSWORD_CONFIRM, {"password": "wrong"}).status_code == 400
    assert post(client, PASSWORD_CONFIRM, {"password": DEFAULT_PASSWORD}).status_code == 204
    assert post(client, DISABLE).status_code == 204


def test_reauth_is_per_session_and_expires(client, setting_override):
    setting_override("security.reauth.actions", ["mfa_disable"])
    user = UserFactory()
    _, codes = enrol(client, user)
    post(client, PASSWORD_CONFIRM, {"password": DEFAULT_PASSWORD})

    phone = Client()
    post(phone, VERIFY, {"mfa_token": mfa_token(user), "code": codes[0]})
    assert post(phone, DISABLE).status_code == 423  # the laptop's confirmation is not the phone's

    # The window has a floor of one minute (zero would make every confirmation useless): age the
    # confirmation past a shortened window instead.
    setting_override("security.reauth.window_minutes", 1)
    UserSession.objects.filter(user=user).update(
        password_confirmed_at=timezone.now() - timedelta(minutes=2)
    )
    assert post(client, DISABLE).status_code == 423
