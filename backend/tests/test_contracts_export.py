"""
The generated frontend contracts are current (FRONTEND_PLATFORM § 24, BUILD_ORDER 8.4 acceptance 1).

Changing a serializer field, a permission, a status, a nav item, a list's ordering_fields or a
public route without regenerating fails here, in CI, naming the command. The committed files are the
boilerplate's own: a linked plugin's contributions are left out, so this passes with or without one.
"""

import json

import pytest

from core import contracts
from core.contracts import PluginScope

pytestmark = pytest.mark.django_db


def test_every_committed_contract_is_current(tmp_path):
    rendered = contracts.render_all()
    assert set(rendered) == {
        "openapi.json",
        "permissions.ts",
        "statuses.ts",
        "ordering.ts",
        "public-routes.ts",
        "localization.ts",
        "nav-manifest.json",
    }
    stale = contracts.stale_files(rendered=rendered)
    assert not stale, (
        f"stale generated contracts: {', '.join(stale)}. Run "
        f"`DJANGO_SETTINGS_MODULE=config.settings_test {contracts.COMMAND}`, then "
        "`npm run contracts` in frontend/, and commit frontend/src/generated/."
    )
    # And a fresh export into an empty directory produces the same bytes (no stale leftovers).
    contracts.write_all(tmp_path, rendered)
    for name in rendered:
        assert (tmp_path / name).read_text(encoding="utf-8") == (
            contracts.GENERATED_DIR / name
        ).read_text(encoding="utf-8")


def test_the_contract_does_not_depend_on_the_deployment(settings):
    settings.PRODUCT_NAME = "Some Product"
    document = contracts.openapi_document(PluginScope.none())
    assert document["info"] == contracts.SCHEMA_INFO
    assert "Some Product" not in json.dumps(document)


def test_the_core_contract_holds_what_the_frontend_types_against():
    document = contracts.openapi_document(PluginScope.none())
    schemas = document["components"]["schemas"]
    assert {"User", "Invitation", "Role"} <= set(schemas)
    assert "cookieAuth" in document["components"]["securitySchemes"]  # cookie auth is described
    assert (
        "InvitationRequest" in schemas
    )  # COMPONENT_SPLIT_REQUEST: request bodies are their own types


def test_plugin_paths_and_their_components_are_pruned():
    schema = {
        "paths": {
            "/api/users/": {"get": {"responses": {"200": {"$ref": "#/components/schemas/User"}}}},
            "/api/notes/": {"get": {"responses": {"200": {"$ref": "#/components/schemas/Note"}}}},
        },
        "components": {
            "schemas": {
                "User": {"properties": {"role": {"$ref": "#/components/schemas/Role"}}},
                "Role": {},
                "Note": {"properties": {"tag": {"$ref": "#/components/schemas/Tag"}}},
                "Tag": {},
            },
            "securitySchemes": {"cookieAuth": {}},
        },
    }
    scope = PluginScope(
        labels=frozenset({"notes"}),
        permission_prefixes=frozenset({"notes"}),
        route_prefixes=frozenset({"notes"}),
    )
    pruned = contracts.prune_schema(schema, scope)
    assert list(pruned["paths"]) == ["/api/users/"]
    assert set(pruned["components"]["schemas"]) == {"User", "Role"}  # Role kept transitively
    assert pruned["components"]["securitySchemes"] == {"cookieAuth": {}}


def test_plugin_codes_statuses_and_routes_are_left_out():
    scope = PluginScope(
        labels=frozenset({"users"}),
        permission_prefixes=frozenset({"users"}),
        route_prefixes=frozenset({"users"}),
    )
    assert '"users.users.view"' not in contracts.render_permissions(scope)
    assert '"rbac.roles.view"' in contracts.render_permissions(scope)
    assert not any(key.startswith("users.") for key in contracts.status_table(scope))
    assert "users:login" not in contracts.render_public_routes(scope)


def test_ordering_lists_only_list_routes_with_ordering_fields():
    table = contracts.ordering_table(PluginScope.none())
    assert table == {
        "core:activity": ["id"]
    }  # the activity log sorts by id; its export route is not a list


def test_permissions_render_as_a_mergeable_interface():
    text = contracts.render_permissions(PluginScope.none())
    assert "export interface PermissionCodes {" in text
    assert '  "users.users.view": true;' in text
    assert "export type PermissionCode = keyof PermissionCodes;" in text
