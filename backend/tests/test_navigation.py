"""
GET /api/me/navigation/: the server-built menu (FRONTEND_PLATFORM.md § 8, BUILD_ORDER 3.4 / 8.2).
A user lacking an item's permission never receives it; a superuser receives every item.
"""

import pytest
from django.test import Client

from core import navigation
from core.registry import NavItem, NavSection, PermissionGroupSpec, PermissionSpec, Registry
from rbac import services as rbac
from tests.factories import DEFAULT_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db

NAV = "/api/me/navigation/"


@pytest.fixture
def menu(monkeypatch):
    """A private registry: the process-wide one is sealed and holds no navigation yet."""
    reg = Registry()
    reg.permissions.register(
        PermissionGroupSpec(
            code="users",
            label="Users",
            module="users",
            permissions=(
                PermissionSpec("users.users.view", "View users"),
                PermissionSpec("users.users.export", "Export users"),
            ),
        )
    )
    reg.navigation.register(
        NavSection(
            key="people",
            label="People",
            module="users",
            order=10,
            items=(
                NavItem("list", "Users", "/users", permission="users.users.view"),
                NavItem("export", "Export", "/users/export", permission="users.users.export"),
            ),
        )
    )
    reg.navigation.register(
        NavSection(
            key="home",
            label="Home",
            module="core",
            order=0,
            items=(
                NavItem("home", "Home", "/", exact=True),
                NavItem("login", "Sign in", "/login", hidden=True, public=True),
            ),
        )
    )
    reg.navigation.register(
        NavSection(
            key="exports",
            label="Exports",
            module="users",
            order=20,
            items=(NavItem("all", "All exports", "/exports", permission="users.users.export"),),
        )
    )
    monkeypatch.setattr(navigation, "registry", reg)
    return reg


def signed_in(*codes, superuser=False) -> Client:
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
    return client


def tree(response) -> dict[str, list[str]]:
    return {s["key"]: [i["key"] for i in s["items"]] for s in response.json()["sections"]}


def test_items_are_filtered_by_effective_permissions_and_empty_sections_dropped(menu):
    response = signed_in("users.users.view").get(NAV)

    assert response.status_code == 200
    # no export item, no exports section
    assert tree(response) == {"home": ["home", "login"], "people": ["list"]}


def test_sections_arrive_in_registry_order_with_labels_and_hrefs(menu):
    sections = signed_in("users.users.view").get(NAV).json()["sections"]

    assert [s["key"] for s in sections] == ["home", "people"]
    assert sections[1] == {
        "key": "people",
        "label": "People",
        "module": "users",
        "items": [
            {
                "key": "list",
                "label": "Users",
                "href": "/users",
                "permission": "users.users.view",
                "hidden": False,
                "public": False,
                "exact": False,
            }
        ],
    }


def test_a_user_with_no_permissions_sees_only_ungated_items(menu):
    assert tree(signed_in().get(NAV)) == {"home": ["home", "login"]}


def test_a_superuser_sees_every_item(menu):
    assert tree(signed_in(superuser=True).get(NAV)) == {
        "home": ["home", "login"],
        "people": ["list", "export"],
        "exports": ["all"],
    }


def test_anonymous_callers_are_refused(menu):
    assert Client().get(NAV).status_code == 401


def test_hidden_and_public_items_reach_the_client_so_the_route_gate_can_match_them(menu):
    home = signed_in().get(NAV).json()["sections"][0]["items"]
    assert [(i["href"], i["hidden"], i["public"], i["exact"]) for i in home] == [
        ("/", False, False, True),
        ("/login", True, True, False),
    ]


# --- The committed manifest the frontend's route checks read (FRONTEND_PLATFORM § 10) ----------
# It is one of the generated contracts now (core/contracts.py, BUILD_ORDER 8.4a): its drift is
# checked with the others in tests/test_contracts_export.py.


def test_the_manifest_is_not_empty():
    assert navigation.full_manifest()["sections"], (
        "no navigation is registered: every page would be denied"
    )


def test_every_gated_item_names_a_declared_permission():
    codes = set(navigation.registry.permissions.codes())
    for section in navigation.full_manifest()["sections"]:
        for item in section["items"]:
            assert item["permission"] is None or item["permission"] in codes, item
