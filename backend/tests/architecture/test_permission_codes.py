"""
Every permission code referenced anywhere ↔ the catalog, both directions (AUTH_BLUEPRINT § 9.3).

Referenced but not declared: the check denies everyone, permanently, while the grant looks right on
the roles screen (§ 9.2 dbx.E002). Declared but never referenced: a right that can be granted and
does nothing, which misleads whoever grants it.

The catalog is `core.registry.registry`, filled by each app's AppConfig.ready() during
django.setup(). References come from tests/architecture/permission_refs.py.
"""

import pytest

from core.registry import registry
from tests.architecture.permission_refs import find_permission_refs

# Codes declared before anything checks them (their endpoints are not built yet). A ratchet: when a
# code here gains a reference, test_declared_ahead_of_use_is_current fails until it is removed.
# Declared before their endpoints exist. Each entry must shrink out as its endpoint lands:
# users.* with the Users CRUD (BUILD_ORDER 1.5) and invitations (after 1.2), rbac.* with 1.4.
DECLARED_AHEAD_OF_USE: frozenset[str] = frozenset(
    {
        "users.invitations.send",
        "users.sessions.revoke",
        "users.users.create",
        "users.users.deactivate",
        "users.users.export",
        "users.users.update",
    }
)


@pytest.fixture(scope="module")
def refs() -> dict[str, list[str]]:
    return find_permission_refs()


@pytest.fixture(scope="module")
def catalog() -> frozenset[str]:
    return registry.permissions.codes()


def _as_lines(codes) -> str:
    return "\n".join(f'    "{code}",' for code in sorted(codes))


def test_the_scan_and_the_catalog_are_not_empty(refs, catalog):
    # Without this, a scanner that finds nothing (or apps that register nothing) passes the rest.
    assert refs, "the scan found no permission references in backend/: is the scanner broken?"
    assert catalog, "the registry catalog is empty: did the apps register in AppConfig.ready()?"


def test_every_referenced_code_is_in_the_catalog(refs, catalog):
    unknown = {code: places for code, places in refs.items() if code not in catalog}
    report = "\n".join(f"  {code}  ← {', '.join(places)}" for code, places in unknown.items())
    assert not unknown, (
        "These codes are referenced but no app declares them. Each one denies everyone, forever.\n"
        "Fix the typo, or declare the code in its module's permissions.py:\n" + report
    )


def test_every_catalog_code_is_referenced_or_declared_ahead(refs, catalog):
    unused = catalog - set(refs) - DECLARED_AHEAD_OF_USE
    assert not unused, (
        "These codes are declared but nothing checks them. Reference each one where it is "
        "enforced, or, if its endpoint is not built yet, add it to DECLARED_AHEAD_OF_USE in "
        f"{__name__.rsplit('.', 1)[-1]}.py:\n" + _as_lines(unused)
    )


def test_declared_ahead_of_use_is_current(refs, catalog):
    now_used = DECLARED_AHEAD_OF_USE & set(refs)
    assert not now_used, (
        "These codes are referenced now. Remove them from DECLARED_AHEAD_OF_USE:\n"
        + _as_lines(now_used)
    )
    undeclared = DECLARED_AHEAD_OF_USE - catalog
    assert not undeclared, (
        "DECLARED_AHEAD_OF_USE lists codes that no app declares. Remove them, or declare them:\n"
        + _as_lines(undeclared)
    )
