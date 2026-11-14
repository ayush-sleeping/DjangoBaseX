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
        {
            "key": "home",
            "label": "Notes",
            "href": "/notes",
            "permission": "notes.notes.view",
            "hidden": False,
            "public": False,
            "exact": False,
        }
    ]
    assert "notes" not in sections(session())


def test_disabling_the_plugin_hides_its_nav_and_routes_without_touching_its_data():
    """BUILD_ORDER 9.1 done-when, on a real plugin: one switch, every surface, the rows stay."""
    from core.plugin_state import set_enabled
    from djx_notes.models import Note

    client = session(*ALL)
    send(client, "post", NOTES, {"title": "Keep me", "body": "Still here"})
    assert client.get(NOTES).status_code == 200
    assert "notes" in [s["key"] for s in client.get(NAV).json()["sections"]]
    before = list(Note.objects.values_list("public_id", "title", "body"))
    assert len(before) == 1

    set_enabled("notes", False, reason="the switch is off for this test")
    listed = client.get(NOTES)
    assert listed.status_code == 403
    assert listed.json()["error"]["code"] == "plugin_disabled"
    assert send(client, "post", NOTES, {"title": "No", "body": "No"}).status_code == 403
    assert "notes" not in [s["key"] for s in client.get(NAV).json()["sections"]]
    assert list(Note.objects.values_list("public_id", "title", "body")) == before  # data intact

    set_enabled("notes", True)
    assert client.get(NOTES).status_code == 200
    assert "notes" in [s["key"] for s in client.get(NAV).json()["sections"]]
    assert list(Note.objects.values_list("public_id", "title", "body")) == before


# --- Data lifecycle (BUILD_ORDER 9.3) -----------------------------------------------------------

BIN = "/api/recycle-bin/"
EDIT = (*ALL, "notes.notes.update")


def test_a_view_holder_gets_404_not_403_when_patching_a_note_they_cannot_see():
    """BUILD_ORDER 9.3 done-when / DB-67: the write path is scoped like the read path."""
    from djx_notes.models import Note

    mine, theirs = session(*EDIT), session(*EDIT)
    note = send(theirs, "post", NOTES, {"title": "Private"}).json()

    assert mine.get(f"{NOTES}{note['public_id']}/").status_code == 404  # they hold notes.view
    patched = send(mine, "patch", f"{NOTES}{note['public_id']}/", {"title": "Hijacked"})
    assert patched.status_code == 404, patched.content
    assert Note.objects.get(public_id=note["public_id"]).title == "Private"

    own = send(theirs, "patch", f"{NOTES}{note['public_id']}/", {"title": "Edited"})
    assert own.status_code == 200 and own.json()["title"] == "Edited"


def test_a_note_records_how_it_came_to_exist_and_ignores_payload_provenance():
    client = session(*ALL)
    made = send(client, "post", NOTES, {"title": "P", "source_ref": "crm:42", "created_via": 1})
    assert made.status_code == 201, made.content
    body = made.json()
    assert body["origin"] == "web" and body["source_ref"] == "crm:42"
    from djx_notes.models import Note

    assert Note.objects.get(public_id=body["public_id"]).created_via is None  # not from the payload
    bad = send(client, "post", NOTES, {"title": "P", "source_ref": "has space"})
    assert bad.status_code == 400


def test_delete_bins_the_note_and_the_bin_restores_it_scoped_to_its_owner():
    from djx_notes.models import Note

    admin_perms = ("core.recycle_bin.manage", *ALL)
    mine, theirs = session(*admin_perms), session(*admin_perms)
    note = send(mine, "post", NOTES, {"title": "Gone"}).json()
    pid = note["public_id"]
    assert send(mine, "delete", f"{NOTES}{pid}/").status_code == 204

    assert mine.get(NOTES).json()["results"] == []  # hidden from the default manager
    assert Note.all_objects.get(public_id=pid).deleted_at is not None
    assert [t["key"] for t in mine.get(BIN).json()["types"]] == ["notes.note"]
    binned = mine.get(BIN, {"type": "notes.note"}).json()["results"]
    assert [r["id"] for r in binned] == [pid] and binned[0]["title"] == "Gone"

    # Another person with the bin permission neither sees it nor can restore it: 404.
    assert theirs.get(BIN, {"type": "notes.note"}).json()["results"] == []
    assert send(theirs, "post", f"{BIN}notes.note/{pid}/restore/").status_code == 404

    restored = send(mine, "post", f"{BIN}notes.note/{pid}/restore/")
    assert restored.status_code == 200, restored.content
    assert [n["public_id"] for n in mine.get(NOTES).json()["results"]] == [pid]


def test_force_delete_needs_the_types_own_delete_code_and_removes_the_row():
    from djx_notes.models import Note

    client = session("core.recycle_bin.manage", "notes.notes.view", "notes.notes.create")
    pid = send(client, "post", NOTES, {"title": "x"}).json()["public_id"]
    Note.objects.get(public_id=pid).soft_delete()
    denied = send(client, "post", f"{BIN}notes.note/{pid}/force-delete/")
    assert denied.status_code == 403 and Note.all_objects.filter(public_id=pid).exists()

    full = session("core.recycle_bin.manage", *ALL)
    pid2 = send(full, "post", NOTES, {"title": "y"}).json()["public_id"]
    Note.objects.get(public_id=pid2).soft_delete()
    assert send(full, "post", f"{BIN}notes.note/{pid2}/force-delete/").status_code == 204
    assert not Note.all_objects.filter(public_id=pid2).exists()


def test_retention_purges_notes_binned_longer_than_the_window():
    from datetime import timedelta

    from django.utils import timezone

    from core.retention import engine
    from djx_notes.models import Note

    client = session(*ALL)
    old = send(client, "post", NOTES, {"title": "old"}).json()["public_id"]
    recent = send(client, "post", NOTES, {"title": "recent"}).json()["public_id"]
    live = send(client, "post", NOTES, {"title": "live"}).json()["public_id"]
    for pid, age in ((old, 100), (recent, 3)):
        note = Note.objects.get(public_id=pid)
        note.soft_delete()
        Note.all_objects.filter(pk=note.pk).update(deleted_at=timezone.now() - timedelta(days=age))

    engine.run(only=["notes.recycle_bin_note"])
    remaining = set(Note.all_objects.values_list("public_id", flat=True))
    assert {str(p) for p in remaining} == {recent, live}  # 90-day default: 100 purged, 3 kept
