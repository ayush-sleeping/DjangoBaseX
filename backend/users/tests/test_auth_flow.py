"""
The cookie-JWT flow end to end (ADR-0009, AUTH_BLUEPRINT Ch. 6, BUILD_ORDER 1.1).

The 1.1 acceptance test is `test_login_round_trip`: anonymous 401 → sign in → recognised →
sign out → 401, plus `test_every_login_failure_answers_identically` (no user enumeration).
"""

import jwt
import pytest
from django.utils import timezone

from tests.factories import DEFAULT_PASSWORD, UserFactory
from users.cookies import REFRESH_PATH, cookie_names
from users.models import LoginAttempt, UserSession

pytestmark = pytest.mark.django_db

LOGIN, REFRESH, LOGOUT, ME = "/api/auth/login/", REFRESH_PATH, "/api/auth/logout/", "/api/auth/me/"
REVOKE_ALL = "/api/auth/sessions/revoke-all/"
NAMES = cookie_names()


def sign_in(client, email, password=DEFAULT_PASSWORD):
    return client.post(
        LOGIN, {"email": email, "password": password}, content_type="application/json"
    )


def csrf(client) -> dict:
    return {"HTTP_X_CSRF_TOKEN": client.cookies[NAMES.csrf].value}


def jti_of(refresh_value: str) -> str:
    return jwt.decode(refresh_value, options={"verify_signature": False})["jti"]


# --- The acceptance criteria --------------------------------------------------------------------


def test_login_round_trip(client):
    user = UserFactory()
    assert client.get(ME).status_code == 401

    response = sign_in(client, user.email)
    assert response.status_code == 204
    assert response.content == b""  # tokens live in cookies, never in a body

    me = client.get(ME)
    assert me.status_code == 200
    assert me.json()["email"] == user.email
    access_before_logout = client.cookies[NAMES.access].value

    assert client.post(LOGOUT, **csrf(client)).status_code == 204
    assert client.get(ME).status_code == 401

    # The old access token is dead too, not merely forgotten by this browser.
    client.cookies[NAMES.access] = access_before_logout
    assert client.get(ME).status_code == 401


def test_every_login_failure_answers_identically(client):
    UserFactory(email="known@example.com")
    UserFactory(email="sleeping@example.com", is_active=False)

    answers = [
        sign_in(client, "known@example.com", "wrong-password"),
        sign_in(client, "nobody@example.com"),
        sign_in(client, "sleeping@example.com"),
        sign_in(client, "not-an-email"),
    ]
    assert {r.status_code for r in answers} == {401}
    assert len({r.content for r in answers}) == 1
    assert answers[0].json()["error"]["code"] == "invalid_credentials"

    # The reason is recorded, never returned.
    reasons = list(LoginAttempt.objects.order_by("id").values_list("failure_reason", flat=True))
    assert reasons == ["bad_password", "unknown_user", "inactive", "unknown_user"]


# --- Cookies and headers ------------------------------------------------------------------------


def test_cookies_are_httponly_secure_lax_and_scoped(client):
    response = sign_in(client, UserFactory().email)
    access, refresh, token = (
        response.cookies[n] for n in (NAMES.access, NAMES.refresh, NAMES.csrf)
    )

    assert NAMES.access.startswith("__Host-") and NAMES.csrf.startswith("__Host-")
    assert access["httponly"] and refresh["httponly"] and not token["httponly"]
    assert all(c["secure"] and c["samesite"] == "Lax" for c in (access, refresh, token))
    assert refresh["path"] == REFRESH_PATH
    assert access["path"] == "/" and token["path"] == "/"


def test_auth_responses_are_never_cached(client):
    assert "no-store" in sign_in(client, UserFactory().email)["Cache-Control"]
    assert "no-store" in client.get(ME)["Cache-Control"]


def test_a_stale_access_cookie_does_not_block_signing_in(client):
    client.cookies[NAMES.access] = "garbage"
    assert sign_in(client, UserFactory().email).status_code == 204


def test_login_sets_last_login(client):
    user = UserFactory()
    sign_in(client, user.email)
    user.refresh_from_db()
    assert user.last_login is not None


# --- CSRF ---------------------------------------------------------------------------------------


def test_unsafe_requests_need_the_session_bound_csrf_token(client):
    sign_in(client, UserFactory().email)

    assert client.post(LOGOUT).status_code == 403
    assert client.post(LOGOUT, HTTP_X_CSRF_TOKEN="planted-value").status_code == 403
    assert client.get(ME).status_code == 200  # safe methods need no token
    assert client.post(LOGOUT, **csrf(client)).status_code == 204


# --- Revocation ---------------------------------------------------------------------------------


def test_deactivating_a_user_ends_their_session(client):
    user = UserFactory()
    sign_in(client, user.email)
    user.is_active = False
    user.save()
    assert client.get(ME).status_code == 401


def test_a_password_change_ends_older_sessions(client):
    user = UserFactory()
    sign_in(client, user.email)
    assert client.get(ME).status_code == 200  # liveness is now cached

    user.password_changed_at = timezone.now()
    user.save()
    assert client.get(ME).status_code == 401


def test_sign_out_everywhere_else_keeps_only_this_session(client, django_user_model):
    from django.test import Client

    user = UserFactory()
    other = Client()
    sign_in(client, user.email)
    sign_in(other, user.email)

    response = client.post(REVOKE_ALL, **csrf(client))
    assert response.json() == {"revoked": 1}
    assert client.get(ME).status_code == 200
    assert other.get(ME).status_code == 401


def test_an_expired_access_token_is_refused(client, settings):
    settings.ACCESS_TOKEN_LIFETIME = -10
    sign_in(client, UserFactory().email)
    assert client.get(ME).status_code == 401


# --- Refresh rotation ---------------------------------------------------------------------------


def test_refresh_rotates_within_one_family(client):
    sign_in(client, UserFactory().email)
    first = client.cookies[NAMES.refresh].value

    assert client.post(REFRESH).status_code == 204
    second = client.cookies[NAMES.refresh].value
    assert jti_of(first) != jti_of(second)

    old, new = UserSession.objects.order_by("id")
    assert old.revoked_reason == "rotated" and old.replaced_by_jti == new.jti
    assert new.family_id == old.family_id and new.revoked_at is None
    assert client.get(ME).status_code == 200


def test_two_tabs_refreshing_together_share_one_successor(client):
    sign_in(client, UserFactory().email)
    first = client.cookies[NAMES.refresh].value
    client.post(REFRESH)
    successor = client.cookies[NAMES.refresh].value

    client.cookies[NAMES.refresh] = first  # the other tab still holds the old token
    response = client.post(REFRESH)

    assert response.status_code == 204
    assert jti_of(client.cookies[NAMES.refresh].value) == jti_of(successor)
    assert UserSession.objects.filter(revoked_at__isnull=True).count() == 1


def test_reuse_after_the_grace_window_revokes_the_whole_family(client, settings):
    settings.REFRESH_ROTATION_GRACE = 0
    sign_in(client, UserFactory().email)
    stolen = client.cookies[NAMES.refresh].value
    client.post(REFRESH)
    live_access = client.cookies[NAMES.access].value

    client.cookies[NAMES.refresh] = stolen
    response = client.post(REFRESH)

    assert response.status_code == 401
    assert response.cookies[NAMES.refresh].value == ""  # cookies cleared
    assert not UserSession.objects.filter(revoked_at__isnull=True).exists()
    assert UserSession.objects.filter(revoked_reason="reuse_detected").exists()
    client.cookies[NAMES.access] = live_access
    assert client.get(ME).status_code == 401  # the legitimate successor is dead too


def test_an_idle_session_cannot_refresh(client, settings):
    sign_in(client, UserFactory().email)
    UserSession.objects.update(
        last_seen_at=timezone.now() - timezone.timedelta(seconds=settings.REFRESH_IDLE_LIFETIME + 1)
    )
    assert client.post(REFRESH).status_code == 401
    assert UserSession.objects.get().revoked_reason == "expired"


def test_an_access_token_is_not_accepted_as_a_refresh_token(client):
    sign_in(client, UserFactory().email)
    client.cookies[NAMES.refresh] = client.cookies[NAMES.access].value
    assert client.post(REFRESH).status_code == 401


def test_refresh_without_a_cookie_is_refused(client):
    assert client.post(REFRESH).status_code == 401
