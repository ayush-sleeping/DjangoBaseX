"""
The example plugin end to end (BUILD_ORDER 3.4): model → migration → permission → route → nav.
Runs with the platform's suite (`cd backend && uv run pytest`) once the plugin is installed.
"""

import pytest
from django.test import Client

from rbac import services as rbac
from tests.factories import DEFAULT_PASSWORD, UserFactory
from users.cookies import cookie_names

pytestmark = pytest.mark.django_db

NOTES, NAV = "/api/notes/", "/api/me/navigation/"


def session(*codes):
    user = UserFactory()
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
    return client


def send(client, method, path, data=None):
    csrf = client.cookies.get(cookie_names().csrf)
    headers = {"HTTP_X_CSRF_TOKEN": csrf.value} if csrf is not None and csrf.value else {}
    return getattr(client, method)(path, data or {}, content_type="application/json", **headers)


ALL = ("notes.notes.view", "notes.notes.create", "notes.notes.delete")


def test_create_list_retrieve_and_delete_a_note():
    client = session(*ALL)

    created = send(client, "post", NOTES, {"title": "First", "body": "Hello"})
    assert created.status_code == 201, created.content
    note = created.json()
    assert note["title"] == "First" and "id" not in note  # public_id only (A15)

    listed = client.get(NOTES).json()
    assert [n["public_id"] for n in listed["results"]] == [note["public_id"]]
    assert client.get(f"{NOTES}{note['public_id']}/").json()["body"] == "Hello"

    assert send(client, "delete", f"{NOTES}{note['public_id']}/").status_code == 204
    assert client.get(f"{NOTES}{note['public_id']}/").status_code == 404


def test_a_person_never_sees_or_deletes_someone_elses_note():
    mine, theirs = session(*ALL), session(*ALL)
    note = send(theirs, "post", NOTES, {"title": "Private"}).json()

    assert mine.get(NOTES).json()["results"] == []
    assert mine.get(f"{NOTES}{note['public_id']}/").status_code == 404
    assert send(mine, "delete", f"{NOTES}{note['public_id']}/").status_code == 404


def test_each_action_needs_its_own_code():
    reader = session("notes.notes.view")
    assert reader.get(NOTES).status_code == 200
    assert send(reader, "post", NOTES, {"title": "x"}).status_code == 403
    assert session().get(NOTES).status_code == 403


def test_an_invalid_note_is_refused_with_the_error_envelope():
    response = send(session(*ALL), "post", NOTES, {"title": ""})
    assert response.status_code == 400
    assert "title" in response.json()["error"]["details"]


def test_the_nav_entry_appears_only_with_the_view_code():
    def sections(client):
        return {s["key"]: s["items"] for s in client.get(NAV).json()["sections"]}

    assert sections(session("notes.notes.view"))["notes"] == [
        {"key": "home", "label": "Notes", "path": "/notes"}
    ]
    assert "notes" not in sections(session())
