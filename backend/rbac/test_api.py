"""/api/rbac/ through real sessions (§ 8, § 10.3): the contract the frontend codes to."""

import pytest
from django.core.checks import run_checks
from django.test import Client, override_settings

from rbac import services
from rbac.models import Role
from tests.factories import DEFAULT_PASSWORD, UserFactory
from users.cookies import cookie_names
from users.models import User

pytestmark = pytest.mark.django_db

NAMES = cookie_names()
ROLES, CATALOG = "/api/rbac/roles/", "/api/rbac/permissions/"


def session(*codes, superuser=False) -> tuple[Client, User]:
    user = UserFactory(is_superuser=superuser)
    if codes:
        role = services.create_role(
            actor=None, name=f"r-{user.pk}", slug=f"r-{user.pk}", permission_codes=codes
        )
        services.assign_role(actor=None, user=user, role=role)
    client = Client()
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )
    return client, user


def send(client, method, path, data=None):
    return getattr(client, method)(
        path,
        data or {},
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=client.cookies[NAMES.csrf].value,
    )


def role_url(role, suffix=""):
    return f"{ROLES}{role.public_id}/{suffix}"


# --- System roles (§ 8.1) -----------------------------------------------------------------------


def test_administrator_holds_the_whole_catalog_and_staff_holds_nothing():
    from core.registry import registry

    admin = Role.objects.get(slug="administrator")
    staff = Role.objects.get(slug="staff")
    assert set(admin.permissions.values_list("code", flat=True)) == set(
        registry.permissions.codes()
    )
    assert admin.is_system and admin.is_elevated
    assert staff.is_system and not staff.permissions.exists()


# --- Reading ------------------------------------------------------------------------------------


def test_the_catalog_needs_its_permission():
    assert session()[0].get(CATALOG).status_code == 403
    response = session("rbac.permissions.view")[0].get(CATALOG)
    assert response.status_code == 200
    assert {g["code"] for g in response.json()} >= {"users", "rbac"}


def test_roles_are_listed_paginated_with_their_codes_and_holders():
    client, _ = session("rbac.roles.view")
    body = client.get(ROLES).json()
    assert {"count", "next", "previous", "results"} <= set(body)
    staff = next(r for r in body["results"] if r["slug"] == "staff")
    assert staff["is_system"] and staff["permissions"] == [] and staff["user_count"] == 0


def test_without_the_view_code_roles_are_invisible_not_forbidden_by_id():
    client, _ = session()
    assert client.get(ROLES).status_code == 403
    staff = Role.objects.get(slug="staff")
    viewer, _ = session("rbac.roles.view", "rbac.roles.update")
    assert viewer.get(role_url(staff)).status_code == 200


# --- Writing roles ------------------------------------------------------------------------------


def test_create_a_role_with_grants():
    client, _ = session("rbac.roles.create", "rbac.roles.view")
    response = send(
        client,
        "post",
        ROLES,
        {"name": "Support", "slug": "support", "permissions": ["users.users.view"]},
    )
    assert response.status_code == 201
    assert response.json()["permissions"] == ["users.users.view"]


def test_only_a_superuser_may_create_an_elevated_role():
    client, _ = session("rbac.roles.create", "rbac.roles.view")
    refused = send(client, "post", ROLES, {"name": "Ops", "slug": "ops", "is_elevated": True})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "elevated_requires_superuser"
    root, _ = session(superuser=True)
    assert (
        send(root, "post", ROLES, {"name": "Ops", "slug": "ops", "is_elevated": True}).status_code
        == 201
    )


def test_only_a_superuser_may_change_an_elevated_role_in_any_way():
    # Found in review: guarding assignment alone let a roles.update holder widen an elevated
    # role's grants, and with them every holder's access.
    ops = services.create_role(actor=None, name="Ops", slug="ops", is_elevated=True)
    editor, _ = session("rbac.roles.view", "rbac.roles.update", "rbac.roles.delete")
    attempts = [
        send(editor, "put", role_url(ops, "permissions/"), {"permissions": ["users.users.view"]}),
        send(editor, "patch", role_url(ops), {"description": "wider"}),
        send(editor, "patch", role_url(ops), {"is_elevated": False}),
        send(editor, "delete", role_url(ops)),
    ]
    assert {r.status_code for r in attempts} == {403}
    assert {r.json()["error"]["code"] for r in attempts} == {"elevated_requires_superuser"}
    assert not ops.permissions.exists()

    root, _ = session(superuser=True)
    widened = send(
        root, "put", role_url(ops, "permissions/"), {"permissions": ["users.users.view"]}
    )
    assert widened.status_code == 200


def test_invalid_input_uses_the_error_envelope():
    client, _ = session("rbac.roles.create", "rbac.roles.view")
    response = send(client, "post", ROLES, {"name": "", "slug": "not a slug"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid"
    assert set(response.json()["error"]["details"]) == {"name", "slug"}


def test_system_roles_cannot_be_renamed_deleted_or_regranted():
    client, _ = session("rbac.roles.view", "rbac.roles.update", "rbac.roles.delete")
    staff = Role.objects.get(slug="staff")
    rename = send(client, "patch", role_url(staff), {"name": "Everyone"})
    delete = send(client, "delete", role_url(staff))
    regrant = send(client, "put", role_url(staff, "permissions/"), {"permissions": []})
    assert {r.status_code for r in (rename, delete, regrant)} == {409}
    assert {r.json()["error"]["code"] for r in (rename, delete, regrant)} == {"system_role"}
    # Description is not the name: a system role's description may still be edited.
    assert send(client, "patch", role_url(staff), {"description": "x"}).status_code == 200


def test_a_role_in_use_cannot_be_deleted():
    client, _ = session("rbac.roles.view", "rbac.roles.delete")
    role = services.create_role(actor=None, name="Held", slug="held")
    services.assign_role(actor=None, user=UserFactory(), role=role)
    response = send(client, "delete", role_url(role))
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "role_in_use",
        "message": "role is held by 1 user(s)",
        "details": {"user_count": 1},
    }
    services.revoke_role(actor=None, user=role.user_roles.get().user, role=role)
    assert send(client, "delete", role_url(role)).status_code == 204


def test_grants_are_replaced_whole_and_answer_with_the_diff():
    client, _ = session("rbac.roles.view", "rbac.roles.update")
    role = services.create_role(
        actor=None, name="Support", slug="support", permission_codes=["users.users.view"]
    )
    response = send(
        client,
        "put",
        role_url(role, "permissions/"),
        {"permissions": ["users.users.update", "users.users.export"]},
    )
    assert response.json() == {
        "added": ["users.users.export", "users.users.update"],
        "removed": ["users.users.view"],
    }
    unknown = send(client, "put", role_url(role, "permissions/"), {"permissions": ["x.y.z"]})
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"] == ["x.y.z"]


def test_turning_on_mfa_required_enforces_it_on_every_holder():
    client, _ = session("rbac.roles.view", "rbac.roles.update")
    role = services.create_role(actor=None, name="Finance", slug="finance")
    holder = UserFactory()
    services.assign_role(actor=None, user=holder, role=role)
    send(client, "patch", role_url(role), {"mfa_required": True})
    holder.refresh_from_db()
    assert holder.mfa_enforced


# --- Assignments --------------------------------------------------------------------------------


def assign_url(user, role=None):
    tail = f"{role.public_id}/" if role else ""
    return f"/api/rbac/users/{user.public_id}/roles/{tail}"


def test_assign_and_revoke_a_role():
    client, _ = session("rbac.roles.view", "rbac.roles.assign", "users.users.view")
    target = UserFactory()
    role = services.create_role(actor=None, name="Support", slug="support")
    assert (
        send(client, "post", assign_url(target), {"role": str(role.public_id)}).status_code == 201
    )
    assert [r["slug"] for r in client.get(assign_url(target)).json()] == ["support"]
    assert send(client, "delete", assign_url(target, role)).status_code == 204


def test_only_a_superuser_may_grant_an_elevated_role():
    client, _ = session("rbac.roles.view", "rbac.roles.assign", "users.users.view")
    target = UserFactory()
    admin = Role.objects.get(slug="administrator")
    refused = send(client, "post", assign_url(target), {"role": str(admin.public_id)})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "elevated_requires_superuser"


def test_the_last_administrator_cannot_be_removed_when_there_is_no_superuser():
    root, root_user = session(superuser=True)
    admin_role = Role.objects.get(slug="administrator")
    last = UserFactory()
    services.assign_role(actor=None, user=last, role=admin_role)
    User.objects.filter(pk=root_user.pk).update(is_superuser=False)  # no superuser left
    services.assign_role(actor=None, user=root_user, role=admin_role)
    services.revoke_role(actor=None, user=root_user, role=admin_role)  # one admin remains: fine

    with pytest.raises(services.LastAdministrator):
        services.revoke_role(actor=None, user=last, role=admin_role)


def test_a_user_the_caller_cannot_see_answers_404():
    client, _ = session("rbac.roles.view", "rbac.roles.assign")  # no users.users.view
    assert client.get(assign_url(UserFactory())).status_code == 404


# --- The gate's boot check (§ 9.2) --------------------------------------------------------------


@override_settings(ROOT_URLCONF="tests.architecture.fake_urls")
def test_e001_flags_api_views_that_skip_the_bases():
    flagged = [e for e in run_checks() if e.id == "dbx.E001"]
    assert len(flagged) == 3  # gated, open and lookup-first in fake_urls are plain APIViews


def test_the_real_urlconf_passes_e001_and_e007():
    assert not {e.id for e in run_checks()} & {"dbx.E001", "dbx.E004", "dbx.E007"}
