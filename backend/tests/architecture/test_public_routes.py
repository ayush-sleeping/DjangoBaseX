"""The PUBLIC_ROUTES ledger stays honest (AUTH_BLUEPRINT.md § 14)."""

from django.urls import NoReverseMatch, reverse

from core.routes import PUBLIC_ROUTES

# Pinned. Opening a route to the internet means editing this set in the same reviewed change.
EXPECTED_PUBLIC = {
    "core:health",
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
    added = set(PUBLIC_ROUTES) - EXPECTED_PUBLIC
    removed = EXPECTED_PUBLIC - set(PUBLIC_ROUTES)
    assert not added, f"new public routes {sorted(added)}: justify each, then update this test"
    assert not removed, f"routes no longer public {sorted(removed)}: remove them from this test"


def test_every_entry_resolves():
    missing = []
    for name in PUBLIC_ROUTES:
        try:
            reverse(name)
        except NoReverseMatch:
            missing.append(name)
    assert not missing, f"PUBLIC_ROUTES names routes that do not exist: {missing}"


def test_every_entry_carries_a_reason():
    blank = [name for name, reason in PUBLIC_ROUTES.items() if len(reason.strip()) < 20]
    assert not blank, f"PUBLIC_ROUTES entries without a real reason: {blank}"
