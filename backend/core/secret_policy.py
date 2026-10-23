"""
What makes a secret acceptable, and how to make one (CONFIGURATION.md § 5; OPERATIONS.md § 2, § 21).

Standard library only, and importable on Python 3.9: config_audit judges secrets with these rules at
settings import, and scripts/setup.sh generates and judges them before Django is installed, on the
host's own python3, through scripts/lib/envfile.py, which imports this module. One definition, so
the script never writes a value the boot refusal would reject.

Formats, by what reads them:
  django   SECRET_KEY: URL-safe (`secrets.token_urlsafe`). Never Django's get_random_secret_key():
           a key that starts with `$` is read by django-environ as a reference (TECH_DEBT DB-25).
  jwt      JWT_SIGNING_KEY: URL-safe, 64 characters.
  fernet   MFA_ENCRYPTION_KEY: 32 random bytes, URL-safe base64, which is exactly Fernet's format.
  hex      database and cache passwords: no @ # / : %, so a DATABASE_URL needs no escaping.
  password the development administrator's password (setup.sh): short enough to type.

    python3 -m core.secret_policy {django,jwt,fernet,hex,password}    # run from backend/
"""

from __future__ import annotations

import base64
import os
import secrets
import sys

# Substring match: distinctive enough that an honest random key never contains them.
DISTINCTIVE = (
    "changeme",
    "change-me",
    "change_me",
    "replace",
    "placeholder",
    "your-",
    "example",
    "insecure",
    "dummy",
    "notsecret",
    "xxxxxxxx",
    "secret-key",
    "django-insecure",
)
# Exact match only: a substring match on "test" would reject honest random keys.
GENERIC = frozenset({"secret", "password", "test", "dev", "key", "admin", "default", "none"})

SECRET_KEY_MIN_LENGTH = 50  # DEPLOYMENT.md § 1
JWT_KEY_MIN_LENGTH = 32  # HS256: at least the hash's 256 bits of key material, as text
DISTINCT_CHARACTERS = 12


def weak_reason(value: str | None, *, min_length: int) -> str | None:
    """Why this secret is unacceptable, or None. Never returns or logs the value."""
    v = (value or "").strip()
    if not v:
        return "is empty"
    if v.lower() in GENERIC:
        return "is a generic placeholder word"
    if any(p in v.lower() for p in DISTINCTIVE):
        return "contains a known placeholder"
    if len(v) < min_length:
        return f"is shorter than {min_length} characters"
    if len(set(v)) < DISTINCT_CHARACTERS:
        return f"has fewer than {DISTINCT_CHARACTERS} distinct characters"
    return None


GENERATORS = {
    "django": lambda: secrets.token_urlsafe(50),
    "jwt": lambda: secrets.token_urlsafe(48),
    "fernet": lambda: base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "hex": lambda: secrets.token_hex(24),
    # The development administrator's sign-in password: typeable, 24 URL-safe characters.
    "password": lambda: secrets.token_urlsafe(18),
}


# The audit's minimum for each kind that it judges by weak_reason().
MIN_LENGTHS = {"django": SECRET_KEY_MIN_LENGTH, "jwt": JWT_KEY_MIN_LENGTH}


def is_placeholder(value: str | None, kind: str) -> bool:
    """
    Empty, or a value the boot refusal would reject: the audit's own rules, not a second list. What
    setup.sh replaces, and what generate() never returns, so the two cannot disagree.
    """
    v = (value or "").strip()
    if not v:
        return True
    if kind in MIN_LENGTHS:
        return weak_reason(v, min_length=MIN_LENGTHS[kind]) is not None
    lowered = v.lower()
    return lowered in GENERIC or any(word in lowered for word in DISTINCTIVE)


def generate(kind: str) -> str:
    """
    A fresh secret of `kind` that the boot refusal accepts and is_placeholder() never flags, for
    every kind. KeyError for an unknown kind. A random key containing "dummy" or "example" by chance
    is astronomically rare, but regenerating costs nothing and makes "setup wrote a key the audit
    refused", or "setup replaced its own key on the next run", impossible.
    """
    while True:
        value = GENERATORS[kind]()
        if not is_placeholder(value, kind):
            return value


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in GENERATORS:
        print(f"usage: python3 -m core.secret_policy {{{','.join(GENERATORS)}}}", file=sys.stderr)
        return 2
    print(generate(argv[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
