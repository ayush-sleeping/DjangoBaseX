"""The permission catalog's boot-time rules (AUTH_BLUEPRINT § 7.1, § 7.2, A6, A7).

Every test builds its own PermissionRegistry(); the process-wide `registry` is never touched.
"""

import ast
from pathlib import Path

import pytest

from core.registry import (
    PermissionGroupSpec,
    PermissionRegistry,
    PermissionSpec,
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


def test_the_registry_holds_a_permission_registry():
    assert isinstance(Registry().permissions, PermissionRegistry)
    assert Registry().permissions is not Registry().permissions


def test_core_registry_imports_only_the_standard_library():
    """§ 2: apps import this to declare permissions, so it must not pull in core, rbac or an app."""
    import sys

    import core.registry

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
