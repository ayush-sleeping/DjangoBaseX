"""The registry seam's boot-time rules (AUTH_BLUEPRINT § 7.1, § 7.2, A6, A7; BUILD_ORDER 1.3).

Every test builds its own registries; the process-wide `registry` is never registered into (it is
sealed after django.setup()).
"""

import ast
import types
from pathlib import Path

import pytest
from django.apps import AppConfig

import core.registry
from core.registry import (
    RESERVED_PREFIXES,
    ApiRoute,
    ApiRouteRegistry,
    HealthCheck,
    HealthRegistry,
    NavigationRegistry,
    NavItem,
    NavSection,
    PermissionGroupSpec,
    PermissionRegistry,
    PermissionSpec,
    PublicRouteRegistry,
    Registry,
    RegistryError,
)


def group(code="billing", module="billing", order=100, label="Billing", perms=None):
    if perms is None:
        perms = (
            PermissionSpec(f"{module}.invoices.view", "View invoices"),
            PermissionSpec(f"{module}.invoices.send", "Send invoices"),
        )
    return PermissionGroupSpec(
        code=code, label=label, module=module, order=order, permissions=perms
    )


@pytest.fixture
def reg():
    return PermissionRegistry()


# --- What a good declaration gives you ----------------------------------------------------------


def test_registered_codes_are_readable(reg):
    reg.register(group())
    assert reg.codes() == {"billing.invoices.view", "billing.invoices.send"}
    assert reg.group_for("billing.invoices.send").code == "billing"


def test_groups_sort_by_order_then_code(reg):
    reg.register(group(code="zeta", module="zeta", order=10))
    reg.register(group(code="beta", module="beta", order=20))
    reg.register(group(code="alpha", module="alpha", order=20))
    assert [g.code for g in reg.groups()] == ["zeta", "alpha", "beta"]


def test_an_unknown_code_is_a_key_error(reg):
    reg.register(group())
    with pytest.raises(KeyError):
        reg.group_for("billing.invoices.delete")


def test_a_group_with_no_permissions_is_allowed(reg):
    # dbx.W002 warns about it; refusing it at boot would be stricter than the design.
    reg.register(group(perms=()))
    assert [g.code for g in reg.groups()] == ["billing"]
    assert reg.codes() == frozenset()


def test_any_action_verb_is_accepted(reg):
    perms = (
        PermissionSpec("users.invitations.send", "Invite users"),
        PermissionSpec("users.sessions.revoke", "Revoke sessions"),
        PermissionSpec("users.users_2.do_thing", "Odd but well-formed"),
    )
    reg.register(group(code="users", module="users", perms=perms))
    assert len(reg.codes()) == 3


# --- Sealing (§ 7.2: seal lazily on first read) -------------------------------------------------


def test_a_new_registry_is_open(reg):
    assert not reg.sealed


@pytest.mark.parametrize("read", ["groups", "codes", "group_for", "seal"])
def test_the_first_read_seals_and_later_registration_raises(reg, read):
    reg.register(group())
    if read == "group_for":
        reg.group_for("billing.invoices.view")
    else:
        getattr(reg, read)()
    assert reg.sealed
    with pytest.raises(RegistryError, match=r"'late'.*sealed"):
        reg.register(group(code="late", module="late"))


def test_a_failed_group_for_still_seals(reg):
    with pytest.raises(KeyError):
        reg.group_for("billing.invoices.view")
    assert reg.sealed


# --- Refusals: each names the offender ----------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "billing.invoices",
        "billing.invoices.view.extra",
        "Billing.invoices.view",
        "billing.Invoices.view",
        "billing.invoices.View",
        "billing.invoices.view ",
        "billing..view",
        "billing.invoices.1view",
        "billing.invoices.view-all",
        "",
    ],
)
def test_a_malformed_code_is_refused(reg, bad):
    with pytest.raises(RegistryError, match="not <module>.<feature>.<action>") as exc:
        reg.register(group(perms=(PermissionSpec(bad, "Label"),)))
    assert repr(bad) in str(exc.value)


def test_a_code_outside_its_module_is_refused(reg):
    with pytest.raises(
        RegistryError, match=r"'users\.users\.view' is outside its module 'billing'"
    ):
        reg.register(group(perms=(PermissionSpec("users.users.view", "View users"),)))


def test_a_duplicate_group_code_is_refused_not_merged(reg):
    reg.register(group())
    with pytest.raises(RegistryError, match="'billing' is already registered"):
        reg.register(group(perms=(PermissionSpec("billing.reports.view", "View reports"),)))
    assert "billing.reports.view" not in reg.codes()  # the first registration stands, unmerged


def test_a_permission_listed_twice_in_one_group_is_refused(reg):
    twice = (
        PermissionSpec("billing.invoices.view", "A"),
        PermissionSpec("billing.invoices.view", "B"),
    )
    with pytest.raises(RegistryError, match="'billing.invoices.view' twice"):
        reg.register(group(perms=twice))


def test_a_permission_declared_by_another_group_is_refused(reg):
    reg.register(group(code="billing", perms=(PermissionSpec("billing.invoices.view", "View"),)))
    with pytest.raises(RegistryError, match="already declared by group 'billing'"):
        reg.register(
            group(code="billing_extra", perms=(PermissionSpec("billing.invoices.view", "View"),))
        )


@pytest.mark.parametrize("label", ["", "   "])
def test_an_empty_permission_label_is_refused(reg, label):
    with pytest.raises(RegistryError, match="'billing.invoices.view' has an empty label"):
        reg.register(group(perms=(PermissionSpec("billing.invoices.view", label),)))


@pytest.mark.parametrize("label", ["", "  "])
def test_an_empty_group_label_is_refused(reg, label):
    with pytest.raises(RegistryError, match="'billing' has an empty label"):
        reg.register(group(label=label))


def test_an_empty_group_code_is_refused(reg):
    with pytest.raises(RegistryError, match="empty code"):
        reg.register(group(code=""))


def test_a_malformed_module_is_refused(reg):
    with pytest.raises(RegistryError, match="module 'Billing'"):
        reg.register(group(module="Billing", perms=()))


def test_something_that_is_not_a_spec_is_refused(reg):
    with pytest.raises(RegistryError, match="expected a PermissionGroupSpec"):
        reg.register({"code": "billing"})
    with pytest.raises(RegistryError, match="not a PermissionSpec"):
        reg.register(group(perms=(("billing.invoices.view", "View"),)))


def test_a_refused_group_leaves_the_catalog_unchanged(reg):
    # The second permission is bad; the first must not have slipped in.
    perms = (PermissionSpec("billing.invoices.view", "View"), PermissionSpec("users.x.view", "X"))
    with pytest.raises(RegistryError):
        reg.register(group(perms=perms))
    assert reg.codes() == frozenset()
    assert reg.groups() == ()


# --- The module itself --------------------------------------------------------------------------


def test_the_registry_holds_every_catalog_each_instance_its_own():
    a, b = Registry(), Registry()
    assert isinstance(a.permissions, PermissionRegistry)
    assert isinstance(a.navigation, NavigationRegistry)
    assert isinstance(a.health, HealthRegistry)
    assert isinstance(a.api_routes, ApiRouteRegistry)
    assert isinstance(a.public_routes, PublicRouteRegistry)
    for name in ("permissions", "navigation", "health", "api_routes", "public_routes"):
        assert getattr(a, name) is not getattr(b, name)


def test_core_registry_imports_only_the_standard_library():
    """§ 2: apps import this to declare permissions, so it must not pull in core, rbac or an app."""
    import sys

    tree = ast.parse(Path(core.registry.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in core/registry.py"
            imported.add(node.module.split(".")[0])
    assert imported, "found no imports at all: the walk is broken"
    assert imported <= sys.stdlib_module_names, (
        f"non-stdlib imports: {imported - sys.stdlib_module_names}"
    )


# === Navigation (1.3) ===========================================================================


def nav(key="billing", module="billing", order=100, label="Billing", items=None):
    if items is None:
        items = (
            NavItem("invoices", "Invoices", "/billing/invoices", "billing.invoices.view"),
            NavItem("help", "Help", "/billing/help"),
        )
    return NavSection(key=key, label=label, module=module, order=order, items=items)


@pytest.fixture
def seam():
    """A whole fresh Registry: navigation needs its sibling permissions."""
    r = Registry()
    r.permissions.register(group())
    return r


def test_sections_sort_by_order_then_key(seam):
    seam.navigation.register(nav(key="zeta", order=10, items=()))
    seam.navigation.register(nav(key="beta", order=20, items=()))
    seam.navigation.register(nav(key="alpha", order=20, items=()))
    assert [s.key for s in seam.navigation.sections()] == ["zeta", "alpha", "beta"]


def test_visible_to_filters_items_and_drops_empty_sections(seam):
    seam.navigation.register(nav())
    seam.navigation.register(
        nav(
            key="reports",
            items=(NavItem("sent", "Sent", "/billing/sent", "billing.invoices.send"),),
        )
    )
    shown = seam.navigation.visible_to(frozenset(), is_superuser=False)
    assert [(s.key, [i.key for i in s.items]) for s in shown] == [("billing", ["help"])]

    shown = seam.navigation.visible_to(frozenset({"billing.invoices.view"}), is_superuser=False)
    assert [(s.key, [i.key for i in s.items]) for s in shown] == [("billing", ["invoices", "help"])]


def test_a_superuser_sees_every_item(seam):
    seam.navigation.register(nav())
    shown = seam.navigation.visible_to(frozenset(), is_superuser=True)
    assert [i.key for i in shown[0].items] == ["invoices", "help"]


def test_a_section_registered_empty_is_never_shown(seam):
    seam.navigation.register(nav(items=()))
    assert seam.navigation.sections()[0].key == "billing"
    assert seam.navigation.visible_to(frozenset(), is_superuser=True) == ()


def test_visible_to_does_not_change_the_catalog(seam):
    seam.navigation.register(nav())
    seam.navigation.visible_to(frozenset(), is_superuser=False)
    assert len(seam.navigation.sections()[0].items) == 2


@pytest.mark.parametrize("read", ["sections", "visible_to", "seal"])
def test_reading_navigation_seals_it_and_its_permissions(seam, read):
    seam.navigation.register(nav())
    if read == "visible_to":
        seam.navigation.visible_to(frozenset(), is_superuser=False)
    else:
        getattr(seam.navigation, read)()
    assert seam.navigation.sealed and seam.permissions.sealed
    with pytest.raises(RegistryError, match=r"'late'.*sealed"):
        seam.navigation.register(nav(key="late", items=()))


def test_an_item_gated_on_an_undeclared_permission_cannot_seal(seam):
    typo = NavItem("invoices", "Invoices", "/billing/invoices", "billing.invoice.view")
    seam.navigation.register(nav(items=(typo,)))
    for _ in range(2):  # every read raises, not just the first
        with pytest.raises(RegistryError, match=r"billing/invoices → 'billing.invoice.view'"):
            seam.navigation.sections()
    assert not seam.navigation.sealed


def test_the_cross_check_uses_its_own_registrys_permissions():
    # Declared in another Registry: it does not count here.
    other = Registry()
    other.permissions.register(group())
    mine = Registry()
    mine.navigation.register(nav())
    with pytest.raises(RegistryError, match="no app declares"):
        mine.navigation.sections()


def test_a_navigation_registry_can_be_built_on_a_bare_permission_registry():
    perms = PermissionRegistry()
    perms.register(group())
    navigation = NavigationRegistry(perms)
    navigation.register(nav())
    assert navigation.sections()[0].items[0].permission == "billing.invoices.view"


def test_a_duplicate_section_key_is_refused(seam):
    seam.navigation.register(nav(items=()))
    with pytest.raises(RegistryError, match="nav section 'billing' is already registered"):
        seam.navigation.register(nav(module="other", items=()))


def test_a_duplicate_item_key_within_a_section_is_refused(seam):
    items = (NavItem("a", "A", "/a"), NavItem("a", "Again", "/b"))
    with pytest.raises(RegistryError, match="lists item 'a' twice"):
        seam.navigation.register(nav(items=items))


def test_the_same_item_key_in_two_sections_is_fine(seam):
    seam.navigation.register(nav(key="one", items=(NavItem("home", "Home", "/one"),)))
    seam.navigation.register(nav(key="two", items=(NavItem("home", "Home", "/two"),)))
    assert len(seam.navigation.sections()) == 2


@pytest.mark.parametrize("path", ["billing", "", "https://example.com/", "//example.com/x"])
def test_an_item_path_must_be_a_site_path(seam, path):
    with pytest.raises(RegistryError, match=f"path {path!r} must be a site path"):
        seam.navigation.register(nav(items=(NavItem("x", "X", path),)))


@pytest.mark.parametrize(
    "spec, message",
    [
        (lambda: nav(label=" "), "nav section 'billing' has an empty label"),
        (lambda: nav(items=(NavItem("x", "", "/x"),)), "item 'x' has an empty label"),
        (lambda: nav(key="Bad Key"), "key must be lowercase"),
        (lambda: nav(items=(NavItem("X", "X", "/x"),)), "item 'X': key must be lowercase"),
        (lambda: nav(module="Billing"), "module 'Billing'"),
        (lambda: nav(items=(NavItem("x", "X", "/x", "nope"),)), "permission 'nope' is not"),
        (lambda: nav(items=(("x", "X", "/x"),)), "which is not a NavItem"),
        (lambda: {"key": "billing"}, "expected a NavSection"),
    ],
)
def test_malformed_sections_are_refused_naming_the_offender(seam, spec, message):
    with pytest.raises(RegistryError, match=message):
        seam.navigation.register(spec())
    assert seam.navigation.sections() == ()  # all or nothing


# === Health (1.3) ===============================================================================


def ok() -> bool:
    return True


def test_health_checks_keep_registration_order():
    health = HealthRegistry()
    health.register(HealthCheck("database", "Database", ok))
    health.register(HealthCheck("cache", "Cache", ok, critical=False))
    assert [(c.key, c.critical) for c in health.checks()] == [("database", True), ("cache", False)]
    assert health.checks()[0].check() is True


def test_reading_health_seals_it():
    health = HealthRegistry()
    health.checks()
    with pytest.raises(RegistryError, match=r"'late'.*sealed"):
        health.register(HealthCheck("late", "Late", ok))


@pytest.mark.parametrize(
    "check, message",
    [
        (HealthCheck("db", "", ok), "health check 'db' has an empty label"),
        (HealthCheck("Db", "Database", ok), "key must be lowercase"),
        (HealthCheck("db", "Database", "not callable"), "check must be callable"),
        (HealthCheck("db", "Database", ok, critical="yes"), "critical must be True or False"),
        ("db", "expected a HealthCheck"),
    ],
)
def test_malformed_health_checks_are_refused(check, message):
    health = HealthRegistry()
    with pytest.raises(RegistryError, match=message):
        health.register(check)
    assert health.checks() == ()


def test_a_duplicate_health_key_is_refused():
    health = HealthRegistry()
    health.register(HealthCheck("db", "Database", ok))
    with pytest.raises(RegistryError, match="health check 'db' is already registered"):
        health.register(HealthCheck("db", "Another database", ok))


# === API routes (1.3) ===========================================================================


def test_routes_sort_by_prefix():
    routes = ApiRouteRegistry()
    routes.register(prefix="zeta", urlconf="zeta.urls")
    routes.register("billing-v2", "billing.api.urls")
    assert routes.routes() == (
        ApiRoute("billing-v2", "billing.api.urls"),
        ApiRoute("zeta", "zeta.urls"),
    )


def test_reading_routes_seals_them():
    routes = ApiRouteRegistry()
    routes.routes()
    with pytest.raises(RegistryError, match=r"'late'.*sealed"):
        routes.register("late", "late.urls")


@pytest.mark.parametrize("prefix", sorted(RESERVED_PREFIXES))
def test_reserved_prefixes_are_refused(prefix):
    with pytest.raises(RegistryError, match=f"/api/{prefix}/ is reserved"):
        ApiRouteRegistry().register(prefix, "plugin.urls")


def test_the_reserved_list_covers_what_core_serves():
    assert {"auth", "rbac", "schema", "docs", "health", "users"} <= RESERVED_PREFIXES


@pytest.mark.parametrize("prefix", ["", "Billing", "billing_v2", "2fa", "-billing", "bill/ing"])
def test_a_malformed_prefix_is_refused(prefix):
    with pytest.raises(RegistryError, match="prefix must be lowercase"):
        ApiRouteRegistry().register(prefix, "plugin.urls")


@pytest.mark.parametrize("urlconf", ["", "billing/urls", "billing..urls", ".urls", "billing.urls."])
def test_a_malformed_urlconf_is_refused(urlconf):
    with pytest.raises(RegistryError, match="is not a dotted module path"):
        ApiRouteRegistry().register("billing", urlconf)


def test_a_duplicate_prefix_is_refused():
    routes = ApiRouteRegistry()
    routes.register("billing", "billing.urls")
    with pytest.raises(RegistryError, match="'billing' is already registered for 'billing.urls'"):
        routes.register("billing", "other.urls")


def test_one_urlconf_cannot_be_mounted_twice():
    routes = ApiRouteRegistry()
    routes.register("billing", "billing.urls")
    with pytest.raises(RegistryError, match=r"already mounted at /api/billing/"):
        routes.register("invoices", "billing.urls")
    assert routes.routes() == (ApiRoute("billing", "billing.urls"),)


# === The 1.3 acceptance test ====================================================================
# "A throwaway app registering a permission group and a nav section appears in both without any
# core file naming it." The app is written exactly as a real one would be: its ready() imports the
# process-wide `registry` by name. The test points that name at a fresh Registry for its duration.


class ThrowawayConfig(AppConfig):
    name = "throwaway"
    label = "throwaway"
    path = str(Path(__file__).parent)  # AppConfig would otherwise look for a real package

    def ready(self) -> None:
        from core.registry import registry

        registry.permissions.register(
            PermissionGroupSpec(
                code="throwaway",
                label="Throwaway",
                module="throwaway",
                permissions=(PermissionSpec("throwaway.widgets.view", "View widgets"),),
            )
        )
        registry.navigation.register(
            NavSection(
                key="throwaway",
                label="Throwaway",
                module="throwaway",
                items=(
                    NavItem("widgets", "Widgets", "/throwaway/widgets", "throwaway.widgets.view"),
                ),
            )
        )
        registry.api_routes.register(prefix="throwaway", urlconf="throwaway.urls")


def test_a_throwaway_app_appears_in_every_catalog_without_core_naming_it(monkeypatch):
    fresh = Registry()
    monkeypatch.setattr(core.registry, "registry", fresh)

    ThrowawayConfig("throwaway", types.ModuleType("throwaway")).ready()

    assert "throwaway.widgets.view" in fresh.permissions.codes()
    assert fresh.permissions.group_for("throwaway.widgets.view").label == "Throwaway"
    assert [s.key for s in fresh.navigation.sections()] == ["throwaway"]
    assert fresh.api_routes.routes() == (ApiRoute("throwaway", "throwaway.urls"),)
    # Gated on its own permission: hidden without it, shown with it.
    assert fresh.navigation.visible_to(frozenset(), is_superuser=False) == ()
    shown = fresh.navigation.visible_to(frozenset({"throwaway.widgets.view"}), is_superuser=False)
    assert [i.key for i in shown[0].items] == ["widgets"]


def test_the_throwaway_app_never_touched_the_process_wide_registry(monkeypatch):
    monkeypatch.setattr(core.registry, "registry", Registry())
    ThrowawayConfig("throwaway", types.ModuleType("throwaway")).ready()
    monkeypatch.undo()
    assert "throwaway.widgets.view" not in core.registry.registry.permissions.codes()


def test_no_core_or_config_file_names_the_throwaway_app():
    backend = Path(__file__).resolve().parents[1]
    offenders = [
        path.relative_to(backend).as_posix()
        for folder in ("core", "config")
        for path in (backend / folder).rglob("*.py")
        if "throwaway" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"core names the plugin it should know nothing about: {offenders}"


# === Public routes (DB-22) ======================================================================

REASON = "Authenticated by the signed callback itself; verified before any read."


def test_public_routes_are_readable_sorted_and_read_only():
    routes = PublicRouteRegistry()
    routes.register("users:login", "The front door. Same answer for every failure.")
    routes.register("billing:payments:callback", REASON)
    routes.register("schema", "  OpenAPI document: describes the surface, holds no data.  ")
    ledger = routes.routes()
    assert list(ledger) == ["billing:payments:callback", "schema", "users:login"]
    assert ledger["schema"] == "OpenAPI document: describes the surface, holds no data."
    with pytest.raises(TypeError):
        ledger["anything"] = "x" * 30  # type: ignore[index]


def test_reading_public_routes_seals_them():
    routes = PublicRouteRegistry()
    routes.routes()
    with pytest.raises(RegistryError, match=r"'late:route'.*sealed"):
        routes.register("late:route", REASON)


@pytest.mark.parametrize(
    "url_name",
    ["", "Users:login", "users:", ":login", "users::login", "users login", "/api/login/", 42],
)
def test_a_malformed_url_name_is_refused(url_name):
    routes = PublicRouteRegistry()
    with pytest.raises(RegistryError, match="not a URL name"):
        routes.register(url_name, REASON)
    assert routes.routes() == {}


@pytest.mark.parametrize("reason", ["", "   ", "Public.", "x" * 19, "  " + "y" * 19 + "  ", None])
def test_a_reason_under_twenty_characters_is_refused(reason):
    routes = PublicRouteRegistry()
    with pytest.raises(RegistryError, match="a sentence a reviewer can disagree with"):
        routes.register("billing:callback", reason)
    assert routes.routes() == {}


def test_exactly_twenty_characters_is_enough():
    routes = PublicRouteRegistry()
    routes.register("billing:callback", "z" * 20)
    assert "billing:callback" in routes.routes()


def test_a_duplicate_names_both_registrants():
    routes = PublicRouteRegistry()

    def register_from(module_name: str) -> None:
        code = compile("routes.register('billing:callback', REASON)", module_name, "exec")
        exec(code, {"__name__": module_name, "routes": routes, "REASON": REASON})

    register_from("billing.apps")
    with pytest.raises(RegistryError) as exc:
        register_from("payments.apps")
    message = str(exc.value)
    assert "'billing:callback' is already registered by billing.apps" in message
    assert "registered again by payments.apps" in message
    assert dict(routes.routes()) == {"billing:callback": REASON}


def test_todays_public_routes_ledger_migrates_cleanly():
    # The ledger moves into this registry next: every entry it holds today must be accepted.
    from core.routes import CORE_PUBLIC_ROUTES
    from users.public_routes import PUBLIC_ROUTES as USERS_PUBLIC_ROUTES

    PUBLIC_ROUTES = {**CORE_PUBLIC_ROUTES, **USERS_PUBLIC_ROUTES}

    routes = PublicRouteRegistry()
    for url_name, reason in PUBLIC_ROUTES.items():
        routes.register(url_name, reason)
    assert set(routes.routes()) == set(PUBLIC_ROUTES)


def test_the_reserved_list_includes_the_extensibility_mounts():
    assert {"me", "meta", "extensions"} <= RESERVED_PREFIXES
