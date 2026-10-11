"""
Signing-key rotation (AUTH_BLUEPRINT § 19.3) and the live-session cap (§ 19.2), BUILD_ORDER 1.7.
Done-when: a token signed with a fallback key still verifies.
"""

import jwt
import pytest
from django.test import Client

from tests.factories import DEFAULT_PASSWORD, UserFactory
from users import tokens
from users.cookies import REFRESH_PATH, cookie_names
from users.models import UserSession

pytestmark = pytest.mark.django_db

NAMES = cookie_names()
OLD, NEW = "old-signing-key-for-rotation-tests", "new-signing-key-for-rotation-tests"


def sign_in(client, user):
    return client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )


def csrf(client):
    return {"HTTP_X_CSRF_TOKEN": client.cookies[NAMES.csrf].value}


def test_tokens_name_their_key_in_the_kid_header(client, settings):
    settings.JWT_SIGNING_KEY = OLD
    sign_in(client, UserFactory())
    header = jwt.get_unverified_header(client.cookies[NAMES.access].value)
    assert header["kid"] == tokens.key_id(OLD)
    assert OLD not in header["kid"]


def test_a_session_survives_rotation_while_the_old_key_is_a_fallback(client, settings):
    settings.JWT_SIGNING_KEY = OLD
    sign_in(client, UserFactory())

    settings.JWT_SIGNING_KEY, settings.JWT_SIGNING_KEY_FALLBACKS = NEW, [OLD]
    assert client.get("/api/auth/me/").status_code == 200  # access token under the old key
    assert client.post(REFRESH_PATH).status_code == 204  # refresh token under the old key
    assert jwt.get_unverified_header(client.cookies[NAMES.access].value)["kid"] == tokens.key_id(
        NEW
    )  # re-issued under the new key
    assert client.post("/api/auth/logout/", **csrf(client)).status_code == 204


def test_the_old_csrf_token_still_works_until_the_cookies_are_rotated(client, settings):
    settings.JWT_SIGNING_KEY = OLD
    sign_in(client, UserFactory())
    settings.JWT_SIGNING_KEY, settings.JWT_SIGNING_KEY_FALLBACKS = NEW, [OLD]
    assert client.post("/api/auth/sessions/revoke-all/", **csrf(client)).status_code == 200


def test_a_two_tab_race_across_a_rotation_is_still_not_theft(client, settings):
    settings.JWT_SIGNING_KEY = OLD
    sign_in(client, UserFactory())
    first = client.cookies[NAMES.refresh].value
    client.post(REFRESH_PATH)  # rotated under OLD: the successor jti was derived with OLD

    settings.JWT_SIGNING_KEY, settings.JWT_SIGNING_KEY_FALLBACKS = NEW, [OLD]
    client.cookies[NAMES.refresh] = first  # the other tab
    assert client.post(REFRESH_PATH).status_code == 204
    assert not UserSession.objects.filter(revoked_reason="reuse_detected").exists()


def test_once_the_fallback_is_dropped_old_tokens_stop_working(client, settings):
    settings.JWT_SIGNING_KEY = OLD
    sign_in(client, UserFactory())
    settings.JWT_SIGNING_KEY, settings.JWT_SIGNING_KEY_FALLBACKS = NEW, []
    assert client.get("/api/auth/me/").status_code == 401


def test_a_token_naming_an_unknown_key_is_refused(client, settings):
    settings.JWT_SIGNING_KEY = OLD
    sign_in(client, UserFactory())
    access = client.cookies[NAMES.access].value
    claims = jwt.decode(access, OLD, algorithms=["HS256"])
    client.cookies[NAMES.access] = jwt.encode(claims, OLD, "HS256", headers={"kid": "nope"})
    assert client.get("/api/auth/me/").status_code == 401


def test_a_new_sign_in_past_the_cap_revokes_the_oldest_session(settings):
    settings.MAX_SESSIONS_PER_USER = 2
    user = UserFactory()
    browsers = [Client() for _ in range(3)]
    for browser in browsers:
        sign_in(browser, user)

    assert UserSession.objects.filter(user=user, revoked_at__isnull=True).count() == 2
    assert browsers[0].get("/api/auth/me/").status_code == 401  # the oldest
    assert browsers[2].get("/api/auth/me/").status_code == 200
    assert UserSession.objects.get(user=user, revoked_at__isnull=False).revoked_reason == "expired"
