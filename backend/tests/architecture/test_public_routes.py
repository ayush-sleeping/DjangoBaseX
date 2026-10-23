"""The public-route ledger (registry.public_routes) stays honest (AUTH_BLUEPRINT.md § 14)."""

from django.urls import NoReverseMatch, reverse

from core.routes import public_routes

# Pinned. Opening a route to the internet means editing this set in the same reviewed change.
EXPECTED_PUBLIC = {
    "core:health",
    "core:health-live",
    "core:health-ready",
    "core:public-config",
    "schema",
    "swagger-ui",
    "users:login",
    "users:refresh",
    "users:password-forgot",
    "users:password-reset",
    "users:mfa-verify",
    "users:invitation-accept",
}


def test_the_ledger_has_not_grown_without_review():
    added = set(public_routes()) - EXPECTED_PUBLIC
    removed = EXPECTED_PUBLIC - set(public_routes())
    assert not added, f"new public routes {sorted(added)}: justify each, then update this test"
    assert not removed, f"routes no longer public {sorted(removed)}: remove them from this test"


def test_every_entry_resolves():
    missing = []
    for name in public_routes():
        try:
            reverse(name)
        except NoReverseMatch:
            missing.append(name)
    assert not missing, f"public_routes() names routes that do not exist: {missing}"


def test_every_entry_carries_a_reason():
    blank = [name for name, reason in public_routes().items() if len(reason.strip()) < 20]
    assert not blank, f"public_routes() entries without a real reason: {blank}"
