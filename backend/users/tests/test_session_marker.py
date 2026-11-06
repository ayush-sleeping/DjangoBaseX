"""
The Path=/ session marker (FRONTEND_PLATFORM § 8.2, TECH_DEBT DB-20, BUILD_ORDER 8.2).

The frontend's proxy lets a page navigation through when the marker is present and the client
refreshes on its first 401; without it, a signed-in user whose /api/-scoped access cookie had
expired would be bounced to sign-in on every page load. So the marker must ride with EVERY
response that sets the session cookies and be cleared by every one that clears them — one test per
path, so a new path that forgets it fails here.
"""

import pytest
from django.test import Client

from rbac.models import Role
from tests.factories import UserFactory
from users.cookies import REFRESH_PATH, cookie_names
from users.models import UserSession

from .test_auth_flow import LOGIN, LOGOUT, csrf, sign_in
from .test_users_api import ACCEPT, NEW_PASSWORD, invite, link_token, send, session

pytestmark = pytest.mark.django_db

NAMES = cookie_names()


def assert_set(response):
    marker = response.cookies[NAMES.session]
    assert marker.value == "1"  # a constant: a marker, never a credential
    assert marker["path"] == "/"  # sent on page navigations, unlike access and refresh
    assert marker["httponly"]
    assert marker["max-age"] == response.cookies[NAMES.refresh]["max-age"]  # lives as the session


def assert_cleared(response):
    assert response.cookies[NAMES.session].value == ""
    assert response.cookies[NAMES.session]["path"] == "/"


def test_set_on_login(client):
    response = sign_in(client, UserFactory().email)
    assert response.status_code == 204
    assert_set(response)


def test_set_on_refresh(client):
    sign_in(client, UserFactory().email)
    response = client.post(REFRESH_PATH)
    assert response.status_code == 204
    assert_set(response)


def test_set_on_invitation_accept(mailoutbox, django_capture_on_commit_callbacks):
    inviter, _ = session("users.invitations.send")
    with django_capture_on_commit_callbacks(execute=True):
        invite(inviter, "marker@example.com", Role.objects.get(slug="staff"))
    response = send(
        Client(), "post", ACCEPT, {"token": link_token(mailoutbox[0]), "password": NEW_PASSWORD}
    )
    assert response.status_code == 204
    assert_set(response)


def test_cleared_on_logout(client):
    sign_in(client, UserFactory().email)
    response = client.post(LOGOUT, **csrf(client))
    assert response.status_code == 204
    assert_cleared(response)


def test_cleared_on_refresh_reuse_detection(client, settings):
    settings.REFRESH_ROTATION_GRACE = 0
    sign_in(client, UserFactory().email)
    stolen = client.cookies[NAMES.refresh].value
    client.post(REFRESH_PATH)
    client.cookies[NAMES.refresh] = stolen
    response = client.post(REFRESH_PATH)
    assert response.status_code == 401
    assert_cleared(response)


def test_cleared_when_the_session_was_revoked_elsewhere(client):
    sign_in(client, UserFactory().email)
    revoked_at = UserSession.objects.get().issued_at
    UserSession.objects.update(revoked_reason="admin", revoked_at=revoked_at)
    response = client.post(REFRESH_PATH)
    assert response.status_code == 401
    assert_cleared(response)


def test_a_login_failure_sets_no_marker(client):
    response = client.post(
        LOGIN, {"email": "nobody@example.com", "password": "x"}, content_type="application/json"
    )
    assert NAMES.session not in response.cookies
