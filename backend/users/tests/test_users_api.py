"""
/api/users/ and invitations through real sessions (BUILD_ORDER 1.5, AUTH_BLUEPRINT § 10.2).
The 1.5 done-when: full CRUD end to end, permission-gated, paginated, tested.
"""

import re
from urllib.parse import unquote

import pytest
from django.test import Client
from django.utils import timezone

from rbac import services as rbac
from rbac.models import Role
from tests.factories import DEFAULT_PASSWORD, UserFactory
from users.cookies import cookie_names
from users.models import Invitation, User, UserSession

pytestmark = pytest.mark.django_db

NAMES = cookie_names()
USERS, INVITES = "/api/users/", "/api/users/invitations/"
ACCEPT, ME = "/api/auth/invitations/accept/", "/api/auth/me/"
NEW_PASSWORD = "a-brand-new-long-passphrase-42"


def session(*codes, superuser=False):
    user = UserFactory(is_superuser=superuser)
    if codes:
        role = rbac.create_role(
            actor=None, name=f"r-{user.pk}", slug=f"r-{user.pk}", permission_codes=codes
        )
        rbac.assign_role(actor=None, user=user, role=role)
    client = Client()
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )
    return client, user


def send(client, method, path, data=None):
    csrf = client.cookies.get(NAMES.csrf)
    headers = {"HTTP_X_CSRF_TOKEN": csrf.value} if csrf is not None and csrf.value else {}
    return getattr(client, method)(path, data or {}, content_type="application/json", **headers)


def url(user, suffix=""):
    return f"{USERS}{user.public_id}/{suffix}"


def link_token(mail) -> str:
    return unquote(re.search(r"token=([^\s\"&<]+)", mail.body).group(1))


# --- Read ---------------------------------------------------------------------------------------


def test_listing_needs_the_view_code_and_is_paginated_and_searchable():
    assert session()[0].get(USERS).status_code == 403
    client, _ = session("users.users.view")
    UserFactory(email="zed@example.com", full_name="Zed Searchable")
    body = client.get(USERS).json()
    assert {"count", "next", "previous", "results"} <= set(body)
    found = client.get(USERS, {"search": "searchable"}).json()["results"]
    assert [u["email"] for u in found] == ["zed@example.com"]
    assert set(found[0]) >= {"public_id", "is_active", "mfa_enabled", "roles"}
    assert "id" not in found[0] and "password" not in found[0]


def test_detail_shows_roles():
    client, _ = session("users.users.view")
    target = UserFactory()
    rbac.assign_role(actor=None, user=target, role=Role.objects.get(slug="staff"))
    assert client.get(url(target)).json()["roles"][0]["slug"] == "staff"


# --- Create and update --------------------------------------------------------------------------


def test_create_makes_an_active_account_and_emails_a_set_password_link(
    mailoutbox, django_capture_on_commit_callbacks
):
    client, _ = session("users.users.create", "users.users.view")
    with django_capture_on_commit_callbacks(execute=True):
        response = send(client, "post", USERS, {"email": "New@Example.com", "full_name": "New"})
    assert response.status_code == 201
    created = User.objects.get(email="new@example.com")
    assert created.is_active and not created.has_usable_password()
    assert "/reset-password?token=" in mailoutbox[0].body

    reset = send(
        Client(),
        "post",
        "/api/auth/password/reset/",
        {"token": link_token(mailoutbox[0]), "password": NEW_PASSWORD},
    )
    assert reset.status_code == 204  # the setup link works through the ordinary reset flow


def test_create_refuses_a_duplicate_email_in_the_envelope():
    client, _ = session("users.users.create")
    UserFactory(email="taken@example.com")
    response = send(client, "post", USERS, {"email": "TAKEN@example.com"})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["email"]


def test_update_changes_the_name_only():
    client, _ = session("users.users.view", "users.users.update")
    target = UserFactory()
    response = send(client, "patch", url(target), {"full_name": "Renamed", "is_superuser": True})
    assert response.json()["full_name"] == "Renamed"
    target.refresh_from_db()
    assert not target.is_superuser  # not a field this endpoint accepts


# --- Deactivate and activate --------------------------------------------------------------------


def test_deactivation_ends_access_and_the_session_record_says_so():
    client, _ = session("users.users.view", "users.users.deactivate")
    target_client, target = session()
    response = send(client, "post", url(target, "deactivate/"), {"reason": "left the company"})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert target_client.get(ME).status_code == 401
    assert UserSession.objects.filter(user=target, revoked_reason="admin").count() == 1

    assert send(client, "post", url(target, "activate/")).json()["is_active"] is True


def test_you_cannot_deactivate_yourself():
    client, me = session("users.users.view", "users.users.deactivate")
    response = send(client, "post", url(me, "deactivate/"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "self_deactivation"


def test_the_last_active_superuser_cannot_be_deactivated():
    client, _ = session("users.users.view", "users.users.deactivate")
    root = UserFactory(is_superuser=True)
    response = send(client, "post", url(root, "deactivate/"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_superuser"


def test_revoking_someone_elses_sessions_needs_its_own_code():
    holder, _ = session("users.users.view")
    target_client, target = session()
    assert send(holder, "post", url(target, "sessions/revoke/")).status_code == 403
    revoker, _ = session("users.users.view", "users.sessions.revoke")
    assert send(revoker, "post", url(target, "sessions/revoke/")).json() == {"revoked": 1}
    assert target_client.get(ME).status_code == 401


# --- Invitations --------------------------------------------------------------------------------


def invite(client, email, role):
    return send(client, "post", INVITES, {"email": email, "role": str(role.public_id)})


def test_an_invitation_creates_the_account_assigns_the_role_and_signs_in(
    mailoutbox, django_capture_on_commit_callbacks
):
    client, _ = session("users.invitations.send")
    role = rbac.create_role(
        actor=None, name="Support", slug="support", permission_codes=["users.users.view"]
    )
    with django_capture_on_commit_callbacks(execute=True):
        sent = invite(client, "Guest@Example.com", role)
    assert sent.status_code == 201
    assert sent.json()["status"] == "pending" and sent.json()["email"] == "guest@example.com"
    assert "/accept-invitation?token=" in mailoutbox[0].body

    browser = Client()
    accepted = send(
        browser,
        "post",
        ACCEPT,
        {"token": link_token(mailoutbox[0]), "password": NEW_PASSWORD, "full_name": "Guest"},
    )
    assert accepted.status_code == 204
    me = browser.get(ME).json()
    assert me["email"] == "guest@example.com" and me["permissions"] == ["users.users.view"]
    assert Invitation.objects.get().status == "accepted"


def test_an_invitation_link_works_once(mailoutbox, django_capture_on_commit_callbacks):
    client, _ = session("users.invitations.send")
    with django_capture_on_commit_callbacks(execute=True):
        invite(client, "once@example.com", Role.objects.get(slug="staff"))
    token = link_token(mailoutbox[0])
    assert (
        send(Client(), "post", ACCEPT, {"token": token, "password": NEW_PASSWORD}).status_code
        == 204
    )
    again = send(Client(), "post", ACCEPT, {"token": token, "password": NEW_PASSWORD})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"


def test_a_weak_password_keeps_the_invitation_usable(
    mailoutbox, django_capture_on_commit_callbacks
):
    client, _ = session("users.invitations.send")
    with django_capture_on_commit_callbacks(execute=True):
        invite(client, "weak@example.com", Role.objects.get(slug="staff"))
    token = link_token(mailoutbox[0])
    weak = send(Client(), "post", ACCEPT, {"token": token, "password": "123"})
    assert weak.json()["error"]["code"] == "invalid_password"
    assert (
        send(Client(), "post", ACCEPT, {"token": token, "password": NEW_PASSWORD}).status_code
        == 204
    )


def test_invitation_guards():
    client, _ = session("users.invitations.send")
    staff = Role.objects.get(slug="staff")
    UserFactory(email="exists@example.com")

    assert invite(client, "exists@example.com", staff).json()["error"]["code"] == "already_a_user"
    assert invite(client, "twice@example.com", staff).status_code == 201
    assert invite(client, "twice@example.com", staff).json()["error"]["code"] == "already_invited"
    elevated = invite(client, "boss@example.com", Role.objects.get(slug="administrator"))
    assert elevated.status_code == 403
    assert elevated.json()["error"]["code"] == "elevated_requires_superuser"


def test_an_expired_invitation_does_not_block_a_new_one():
    client, _ = session("users.invitations.send")
    staff = Role.objects.get(slug="staff")
    invite(client, "late@example.com", staff)
    Invitation.objects.update(expires_at=timezone.now())
    assert invite(client, "late@example.com", staff).status_code == 201
    assert [i.status for i in Invitation.objects.order_by("pk")] == ["revoked", "pending"]


def test_revoke_kills_the_link(mailoutbox, django_capture_on_commit_callbacks):
    client, _ = session("users.invitations.send")
    with django_capture_on_commit_callbacks(execute=True):
        sent = invite(client, "nope@example.com", Role.objects.get(slug="staff"))
    revoke_url = f"{INVITES}{sent.json()['public_id']}/revoke/"
    assert send(client, "post", revoke_url).json()["status"] == "revoked"
    assert send(client, "post", revoke_url).json()["error"]["code"] == "not_pending"
    token = link_token(mailoutbox[0])
    assert (
        send(Client(), "post", ACCEPT, {"token": token, "password": NEW_PASSWORD}).status_code
        == 400
    )


def test_listing_invitations_needs_its_code():
    assert session()[0].get(INVITES).status_code == 403
    client, _ = session("users.invitations.send")
    assert client.get(INVITES).json()["count"] == 0
