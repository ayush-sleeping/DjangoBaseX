"""
BUILD_ORDER 9.4 done-when 2: a bulk action over "all matching" touches exactly the rows the list
shows. Demonstrated on the real users resource (deactivate), through the real list pipeline.
"""

import pytest
from rest_framework.test import APIClient

from core.models import ActivityLog
from rbac import services as rbac
from tests.factories import UserFactory
from users.models import User
from users.models.user import UserQuerySet

pytestmark = pytest.mark.django_db

LIST = "/api/users/"
BULK = "/api/users/bulk/deactivate/"


def make_caller(*codes, email="admin@example.com"):
    role = rbac.create_role(actor=None, name="r", slug="r", permission_codes=list(codes))
    caller = UserFactory(email=email)
    rbac.assign_role(actor=None, user=caller, role=role)
    client = APIClient()
    client.force_authenticate(user=caller)
    return caller, client


def admin():
    return make_caller("users.users.view", "users.users.deactivate")


def listed_ids(client, **params):
    response = client.get(LIST, params)
    assert response.status_code == 200, response.content
    return {row["public_id"] for row in response.json()["results"]}


@pytest.fixture
def narrowed_scope(monkeypatch):
    """The caller can never see 'hidden-*' rows and can see but not write 'locked-*' rows."""
    original = UserQuerySet.visible_to
    monkeypatch.setattr(
        UserQuerySet,
        "visible_to",
        lambda self, user: original(self, user).exclude(email__startswith="hidden-"),
    )
    monkeypatch.setattr(
        UserQuerySet,
        "writable_by",
        lambda self, user: self.visible_to(user).exclude(email__startswith="locked-"),
    )


def test_all_matching_touches_exactly_the_rows_the_list_shows(narrowed_scope):
    _, client = admin()
    wanted = [UserFactory(full_name=f"Alpha {i}", email=f"alpha{i}@x.test") for i in range(3)]
    UserFactory(full_name="Alpha Gone", email="gone@x.test", is_active=False)  # filtered out
    UserFactory(full_name="Beta", email="beta@x.test")  # filtered out by search
    UserFactory(full_name="Alpha Hidden", email="hidden-alpha@x.test")  # never visible
    everyone_else = set(
        User.objects.exclude(pk__in=[u.pk for u in wanted]).values_list("pk", flat=True)
    )
    filters = {"is_active": "true", "search": "alpha"}

    shown = listed_ids(client, **filters)
    assert shown == {str(u.public_id) for u in wanted}  # the list itself, before any bulk call

    response = client.post(
        BULK, {"all_matching": True, "filters": filters, "expected_count": 3}, format="json"
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["requested"], body["affected"], body["skipped"]) == (3, 3, 0)

    deactivated_now = {
        str(u.public_id)
        for u in User.objects.filter(pk__in=[w.pk for w in wanted], is_active=False)
    }
    assert deactivated_now == shown  # exactly the listed rows were touched
    assert set(
        User.objects.filter(pk__in=everyone_else, is_active=False).values_list("email", flat=True)
    ) == {"gone@x.test"}  # nothing else changed (it was already inactive)
    assert User.objects.get(email="hidden-alpha@x.test").is_active
    assert User.objects.get(email="beta@x.test").is_active


def test_the_bulk_filters_are_the_lists_filters_so_a_typo_is_a_400_not_everything():
    _, client = admin()
    UserFactory()
    response = client.post(BULK, {"all_matching": True, "filters": {"nope": "1"}}, format="json")
    assert response.status_code == 400
    assert client.get(LIST, {"nope": "1"}).status_code == 400  # the list refuses the same way
    assert User.objects.filter(is_active=False).count() == 0


def test_a_changed_selection_is_a_409_and_nothing_is_touched():
    _, client = admin()
    UserFactory(full_name="Alpha 1")
    response = client.post(
        BULK,
        {"all_matching": True, "filters": {"search": "alpha"}, "expected_count": 5},
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "bulk_selection_changed"
    assert User.objects.filter(is_active=False).count() == 0


def test_protected_and_unwritable_rows_are_skipped_with_a_reason_the_rest_succeed(narrowed_scope):
    caller, client = admin()
    ok = UserFactory(email="ok@x.test")
    locked = UserFactory(email="locked-1@x.test")
    hidden = UserFactory(email="hidden-1@x.test")
    inactive = UserFactory(email="idle@x.test", is_active=False)
    response = client.post(
        BULK,
        {"ids": [str(u.public_id) for u in (ok, locked, hidden, inactive, caller)]},
        format="json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    reasons = {r["id"]: r["code"] for r in body["skipped_reasons"]}
    assert reasons == {
        str(locked.public_id): "not_writable",
        str(hidden.public_id): "not_found",  # an unseen id is never confirmed to exist
        str(inactive.public_id): "already_inactive",
        str(caller.public_id): "self_deactivation",
    }
    assert (body["requested"], body["affected"]) == (5, 1)
    ok.refresh_from_db()
    assert not ok.is_active
    for untouched in (locked, hidden, caller):
        untouched.refresh_from_db()
        assert untouched.is_active


def test_every_row_and_the_summary_share_one_batch_and_the_summary_is_audited():
    _, client = admin()
    users = [UserFactory() for _ in range(2)]
    body = client.post(BULK, {"ids": [str(u.public_id) for u in users]}, format="json").json()
    rows = ActivityLog.objects.filter(batch_id=body["batch_id"])
    assert {r.action for r in rows} >= {"users.user.deactivated", "core.bulk.completed"}
    assert rows.filter(action="users.user.deactivated").count() == 2


def test_the_actions_own_permission_is_required():
    _, client = make_caller("users.users.view")
    assert client.post(BULK, {"ids": ["x"]}, format="json").status_code == 403
    assert client.post("/api/users/bulk/explode/", {"ids": ["x"]}, format="json").status_code in (
        403,
        404,
    )


def test_ids_and_all_matching_together_are_refused():
    _, client = admin()
    assert client.post(BULK, {"ids": ["x"], "all_matching": True}, format="json").status_code == 400
    assert client.post(BULK, {}, format="json").status_code == 400
