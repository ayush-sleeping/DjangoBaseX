"""RBAC: seeding, the backend and its cache, the bypass audit, scoping, and the boot checks."""

import logging

import pytest
from django.contrib.auth.models import Group as DjangoGroup
from django.contrib.auth.models import Permission as DjangoPermission
from django.core.checks import run_checks
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from core.permissions import has_permission
from core.querysets import VisibleToQuerySet
from core.registry import PermissionGroupSpec, PermissionSpec, registry
from rbac import seeding, services
from rbac.models import Permission, PermissionGroup, RolePermission
from rbac.selectors import bump_version
from tests.factories import UserFactory
from users.models import User

pytestmark = pytest.mark.django_db


def role_with(*codes, **fields):
    role = services.create_role(
        name=fields.pop("name", "Editors"), slug=fields.pop("slug", "editors"), **fields
    )
    services.set_grants(role, set(codes))
    return role


def fresh(user):
    """The same user as a new request would load it (no request-local permission cache)."""
    return User.objects.get(pk=user.pk)


# --- Seeding (§ 7.3) ----------------------------------------------------------------------------


def test_migrate_seeds_the_whole_catalog():
    assert set(Permission.objects.values_list("code", flat=True)) == set(
        registry.permissions.codes()
    )
    assert PermissionGroup.objects.filter(code__in=["users", "rbac"]).count() == 2


def test_seeding_twice_changes_nothing():
    assert not seeding.sync_catalog().changed


def test_a_code_that_leaves_the_catalog_is_deprecated_never_deleted(monkeypatch):
    role = role_with("users.users.export")
    trimmed = tuple(
        PermissionGroupSpec(
            g.code,
            g.label,
            g.module,
            g.order,
            tuple(p for p in g.permissions if p.code != "users.users.export"),
        )
        for g in registry.permissions.groups()
    )
    monkeypatch.setattr(registry.permissions, "groups", lambda: trimmed)

    report = seeding.sync_catalog()
    assert report.deprecated == ["users.users.export"]
    assert Permission.objects.get(code="users.users.export").is_deprecated
    assert RolePermission.objects.filter(role=role).exists()  # the grant survived

    monkeypatch.undo()
    assert seeding.sync_catalog().restored == ["users.users.export"]


# --- The backend and its cache (§ 7.4) ----------------------------------------------------------


def test_a_user_holds_the_union_of_their_roles_and_nothing_else():
    user = UserFactory()
    assert not user.has_perm("users.users.view")

    services.assign_role(user, role_with("users.users.view"))
    services.assign_role(user, role_with("rbac.roles.view", name="Auditors", slug="auditors"))
    user = fresh(user)
    assert user.has_perm("users.users.view") and user.has_perm("rbac.roles.view")
    assert not user.has_perm("users.users.update")


def test_a_grant_change_takes_effect_without_a_restart():
    user = UserFactory()
    role = role_with("users.users.view")
    services.assign_role(user, role)
    assert fresh(user).has_perm("users.users.view")  # now cached

    services.set_grants(role, set())
    assert not fresh(user).has_perm("users.users.view")

    services.set_grants(role, {"users.users.view"})
    services.revoke_role(user, role)
    assert not fresh(user).has_perm("users.users.view")


def test_inactive_users_and_deprecated_permissions_grant_nothing():
    user = UserFactory()
    services.assign_role(user, role_with("users.users.view"))
    Permission.objects.filter(code="users.users.view").update(is_deprecated=True)
    bump_version()
    assert not fresh(user).has_perm("users.users.view")

    Permission.objects.update(is_deprecated=False)
    bump_version()
    user.is_active = False
    user.save()
    assert not fresh(user).has_perm("users.users.view")


def test_granting_an_unknown_code_is_refused():
    role = role_with()
    with pytest.raises(ValueError, match="users.users.vew"):
        services.set_grants(role, {"users.users.vew"})


def test_django_groups_and_auth_permissions_are_not_a_second_grant_path():
    user = UserFactory()
    group = DjangoGroup.objects.create(name="sneaky")
    group.permissions.set(DjangoPermission.objects.filter(codename="change_user"))
    user.groups.add(group)
    assert not fresh(user).has_perm("users.change_user")


def test_every_superuser_bypass_is_audited(caplog):
    root = UserFactory(is_superuser=True)
    with caplog.at_level(logging.INFO, logger="audit"):
        assert root.has_perm("users.users.view")
    bypasses = [r for r in caplog.records if r.getMessage() == "authz.superuser_bypass"]
    assert len(bypasses) == 1
    assert bypasses[0].audit_meta == {"permission": "users.users.view"}


# --- Roles that require MFA ---------------------------------------------------------------------


def test_an_mfa_required_role_enforces_mfa_until_it_is_revoked():
    user = UserFactory()
    role = role_with(name="Admins", slug="admins", mfa_required=True)
    services.assign_role(user, role)
    assert fresh(user).mfa_enforced
    services.revoke_role(user, role)
    assert not fresh(user).mfa_enforced


# --- Layer 1: HasPermission (§ 7.5) -------------------------------------------------------------


class GatedView(APIView):
    permission_classes = [has_permission("users.users.view")]

    def get(self, request):
        from rest_framework.response import Response

        return Response({"ok": True})


def call_gated(user):
    request = APIRequestFactory().get("/gated/")
    force_authenticate(request, user=user)
    return GatedView.as_view()(request).status_code


def test_has_permission_refuses_without_the_code_and_allows_with_it():
    user = UserFactory()
    assert call_gated(fresh(user)) == 403
    services.assign_role(user, role_with("users.users.view"))
    assert call_gated(fresh(user)) == 200


def test_has_permission_needs_at_least_one_code():
    with pytest.raises(ValueError):
        has_permission()


# --- Layer 2: visible_to (§ 7.6) ----------------------------------------------------------------


def test_visible_to_without_an_implementation_fails_loudly():
    with pytest.raises(NotImplementedError, match="must implement visible_to"):
        VisibleToQuerySet(model=User).visible_to(UserFactory())


def test_users_see_themselves_until_they_may_view_users():
    me, other = UserFactory(), UserFactory()
    assert list(User.objects.visible_to(fresh(me))) == [me]

    services.assign_role(me, role_with("users.users.view"))
    assert set(User.objects.visible_to(fresh(me))) == {me, other}


def test_visible_to_is_empty_for_anonymous():
    from django.contrib.auth.models import AnonymousUser

    UserFactory()
    assert not User.objects.visible_to(AnonymousUser()).exists()


# --- /me ----------------------------------------------------------------------------------------


def test_me_lists_effective_codes_and_the_whole_catalog_for_a_superuser(client):
    from tests.factories import DEFAULT_PASSWORD

    user = UserFactory()
    services.assign_role(user, role_with("users.users.view"))
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )
    assert client.get("/api/auth/me/").json()["permissions"] == ["users.users.view"]

    from users.serializers import MeSerializer

    root = UserFactory(is_superuser=True)
    assert set(MeSerializer(root).data["permissions"]) == set(registry.permissions.codes())


# --- Boot checks (§ 9.2) ------------------------------------------------------------------------


def test_e006_refuses_a_backend_that_could_grant_permissions(settings):
    settings.AUTHENTICATION_BACKENDS = [
        "rbac.backends.RBACBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]
    assert "dbx.E006" in {e.id for e in run_checks()}


def test_e005_refuses_a_per_process_cache_outside_debug(settings):
    settings.DEBUG = False
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    assert "dbx.E005" in {e.id for e in run_checks()}


def test_the_shipped_backends_pass_e006():
    assert "dbx.E006" not in {e.id for e in run_checks()}


def test_e005_accepts_a_per_process_cache_in_development(settings):
    settings.DEBUG = True
    assert "dbx.E005" not in {e.id for e in run_checks()}


def test_permission_specs_are_importable_without_rbac():
    # Apps declare permissions through core alone (AUTH_BLUEPRINT Ch. 2).
    assert PermissionSpec.__module__ == "core.registry"
