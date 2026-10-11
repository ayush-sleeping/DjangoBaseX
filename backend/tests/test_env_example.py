"""The shipped backend/.env.example can never boot in production (CONFIGURATION.md § 5).

Every secret in it is a placeholder that weak_reason() refuses. The secret keys are named
explicitly, and a ratchet fails when the file gains a secret-looking key this test does not cover.
"""

import re
from pathlib import Path

import pytest

from core.config_audit import JWT_KEY_MIN_LENGTH, SECRET_KEY_MIN_LENGTH, audit, weak_reason

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

# The secrets, and the floor each is held to.
SECRETS = {
    "SECRET_KEY": SECRET_KEY_MIN_LENGTH,
    "JWT_SIGNING_KEY": JWT_KEY_MIN_LENGTH,
    "MFA_ENCRYPTION_KEY": JWT_KEY_MIN_LENGTH,  # a Fernet key is 44 characters
}
# Keys whose names look secret-ish but are not secrets. Each line is a reviewed decision.
NOT_SECRETS = {
    "AUTH_COOKIE_PREFIX": "a cookie-name prefix",
}
SECRET_LOOKING = re.compile(r"(SECRET|PASSWORD|TOKEN|_KEY$|KEY_)")


def active_entries() -> dict[str, str]:
    """KEY=VALUE lines that are not commented out. The values are placeholders by design."""
    entries = {}
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$", line)
        if match:
            entries[match.group(1)] = match.group(2).strip().strip("'\"")
    return entries


def test_the_example_file_exists_and_parses():
    entries = active_entries()
    assert "SECRET_KEY" in entries, "the parser found nothing: has the file moved?"


@pytest.mark.parametrize("key", sorted(SECRETS))
def test_every_secret_placeholder_is_refused(key):
    entries = active_entries()
    assert key in entries, f"{key} is no longer in .env.example: update SECRETS here"
    assert weak_reason(entries[key], min_length=SECRETS[key]) is not None, (
        f".env.example ships a {key} that would pass the production audit"
    )


def test_every_secret_looking_key_is_covered():
    uncovered = sorted(
        key
        for key in active_entries()
        if SECRET_LOOKING.search(key) and key not in SECRETS and key not in NOT_SECRETS
    )
    assert not uncovered, (
        f".env.example has secret-looking keys this test does not check: {uncovered}. Add each "
        "to SECRETS (and make sure its placeholder is refused) or to NOT_SECRETS with a reason."
    )


def test_the_example_as_a_production_namespace_is_refused():
    entries = active_entries()
    ns = {
        "APP_ENV": "production",
        "SECRET_KEY": entries.get("SECRET_KEY", ""),
        "JWT_SIGNING_KEY": entries.get("JWT_SIGNING_KEY", ""),
    }
    problems, _ = audit(ns)
    refused = {f.key for f in problems if f.code == "cfg.E003"}
    assert {"SECRET_KEY", "JWT_SIGNING_KEY"} <= refused
