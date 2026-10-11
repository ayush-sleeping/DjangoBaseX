"""Password reset and the password-change cascade (AUTH_BLUEPRINT § 6.6–6.7, Ch. 18)."""

import re
from urllib.parse import unquote

import pytest
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from tests.factories import DEFAULT_PASSWORD, UserFactory
from users import emails
from users.models import PasswordResetToken, UserSession

pytestmark = pytest.mark.django_db

FORGOT, RESET, ME = "/api/auth/password/forgot/", "/api/auth/password/reset/", "/api/auth/me/"
NEW_PASSWORD = "a-brand-new-long-passphrase-42"


def forgot(client, email):
    return client.post(FORGOT, {"email": email}, content_type="application/json")


def reset(client, token, password=NEW_PASSWORD):
    return client.post(
        RESET, {"token": token, "password": password}, content_type="application/json"
    )


def request_token(client, django_capture_on_commit_callbacks, mailoutbox, email) -> str:
    with django_capture_on_commit_callbacks(execute=True):
        assert forgot(client, email).status_code == 204
    match = re.search(r"token=([^\s\"&<]+)", mailoutbox[-1].body)
    return unquote(match.group(1))


def sign_in(client, email, password=DEFAULT_PASSWORD):
    return client.post(
        "/api/auth/login/", {"email": email, "password": password}, content_type="application/json"
    )


# --- Forgot: no enumeration, mail only where it belongs -----------------------------------------


def test_forgot_answers_204_for_every_address_and_mails_only_active_accounts(
    client, mailoutbox, django_capture_on_commit_callbacks
):
    UserFactory(email="known@example.com")
    UserFactory(email="sleeping@example.com", is_active=False)

    with django_capture_on_commit_callbacks(execute=True):
        answers = [
            forgot(client, a)
            for a in ("Known@Example.com", "nobody@example.com", "sleeping@example.com")
        ]

    assert {r.status_code for r in answers} == {204}
    assert len({r.content for r in answers}) == 1
    assert [m.to for m in mailoutbox] == [["known@example.com"]]
    assert PasswordResetToken.objects.count() == 1


def test_the_link_uses_frontend_base_url_and_the_token_is_never_stored(
    client, mailoutbox, django_capture_on_commit_callbacks, settings
):
    settings.FRONTEND_BASE_URL = "https://app.example.com"
    user = UserFactory()
    token = request_token(client, django_capture_on_commit_callbacks, mailoutbox, user.email)

    assert "https://app.example.com/reset-password?token=" in mailoutbox[0].body
    assert mailoutbox[0].alternatives, "the HTML part is missing"
    assert not PasswordResetToken.objects.filter(token_hash=token).exists()


def test_a_mail_failure_still_answers_204(
    client, mailoutbox, django_capture_on_commit_callbacks, monkeypatch
):
    def explode(*args, **kwargs):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(emails, "send_password_reset", explode)
    user = UserFactory()
    with django_capture_on_commit_callbacks(execute=True):
        assert forgot(client, user.email).status_code == 204


# --- Reset --------------------------------------------------------------------------------------


def test_reset_sets_the_password_and_ends_every_session(
    client, mailoutbox, django_capture_on_commit_callbacks
):
    from django.test import Client

    user = UserFactory()
    other_browser = Client()
    sign_in(other_browser, user.email)
    assert other_browser.get(ME).status_code == 200

    token = request_token(client, django_capture_on_commit_callbacks, mailoutbox, user.email)
    assert reset(client, token).status_code == 204

    assert other_browser.get(ME).status_code == 401
    assert UserSession.objects.filter(revoked_reason="password_changed").count() == 1
    assert sign_in(client, user.email, NEW_PASSWORD).status_code == 204
    assert sign_in(Client(), user.email, DEFAULT_PASSWORD).status_code == 401


def test_a_reset_link_works_once_and_kills_every_other_link(
    client, mailoutbox, django_capture_on_commit_callbacks
):
    user = UserFactory()
    first = request_token(client, django_capture_on_commit_callbacks, mailoutbox, user.email)
    second = request_token(client, django_capture_on_commit_callbacks, mailoutbox, user.email)

    assert reset(client, second).status_code == 204
    replay, older = reset(client, second), reset(client, first)
    assert replay.status_code == older.status_code == 400
    assert replay.json()["error"]["code"] == older.json()["error"]["code"] == "invalid_token"


def test_an_expired_or_unknown_token_is_refused_identically(
    client, mailoutbox, django_capture_on_commit_callbacks
):
    user = UserFactory()
    token = request_token(client, django_capture_on_commit_callbacks, mailoutbox, user.email)
    PasswordResetToken.objects.update(expires_at=timezone.now())

    expired, unknown = reset(client, token), reset(client, "not-a-real-token")
    assert expired.status_code == unknown.status_code == 400
    assert expired.content == unknown.content


def test_a_weak_password_is_refused_and_the_link_stays_usable(
    client, mailoutbox, django_capture_on_commit_callbacks
):
    user = UserFactory()
    token = request_token(client, django_capture_on_commit_callbacks, mailoutbox, user.email)

    weak = reset(client, token, password="123")
    assert weak.status_code == 400
    assert weak.json()["error"]["code"] == "invalid_password"
    assert weak.json()["error"]["details"]
    assert reset(client, token).status_code == 204


# --- The cascade, whatever path changed the password --------------------------------------------


def test_any_password_change_ends_sessions_not_only_a_reset(client):
    user = UserFactory()
    sign_in(client, user.email)

    user.set_password("changed-by-an-admin-or-a-shell")
    user.save()

    user.refresh_from_db()
    assert user.password_changed_at is not None
    assert client.get(ME).status_code == 401
    # Revoked, not merely outdated: the sessions screen and "where am I signed in" depend on it.
    assert UserSession.objects.get(user=user).revoked_reason == "password_changed"


def test_a_login_time_hash_upgrade_is_not_a_password_change(client, settings):
    # Logging in with an old-format hash re-hashes it. That must not sign anyone out.
    settings.PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    ]
    user = UserFactory()
    type(user).objects.filter(pk=user.pk).update(
        password=make_password(DEFAULT_PASSWORD, hasher="pbkdf2_sha256")
    )

    assert sign_in(client, user.email).status_code == 204
    user.refresh_from_db()
    assert user.password.startswith("md5$")  # upgraded
    assert user.password_changed_at is None
    assert client.get(ME).status_code == 200
