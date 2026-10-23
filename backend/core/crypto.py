"""
The encryption service: the ONE place anything is encrypted at rest (JOBS_AND_INTEGRATIONS.md § 25;
BUILD 6.3; closes TECH_DEBT DB-33).

    token = encrypt("JBSWY3DP…", purpose="mfa_totp")      # newest key; a str Fernet token
    plain = decrypt(token, purpose="mfa_totp")   # tries every key; DecryptionError on failure —
                                                 # never the input and never None
    mask(value)                                  # "" · "••••••••" · "••••1234" · UNREADABLE

FIELD_ENCRYPTION_KEYS is a list of Fernet keys, NEWEST FIRST, separate from SECRET_KEY and
JWT_SIGNING_KEY and never derived from either (rotating one must not brick the others; dbx.crypto
refuses equality). The key actually used is HKDF-SHA256 over the master key with
info=f"{PRODUCT_SLUG}:{purpose}:v1", so one purpose's ciphertext cannot be decrypted as another's.
⚠️ That also means the info label — the slug included — must never change once anything is
encrypted: renaming PRODUCT_SLUG with stored secrets makes the boot self-test refuse to start,
loudly, which is the recoverable version of that mistake.

Purposes are registered constants (PURPOSES): the boot self-test probes each one in
CoreConfig.ready() without reading any catalog, and registry.encrypted_fields refuses a purpose not
listed here.
"""

import base64
import functools
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

logger = logging.getLogger("core.crypto")

# Every purpose anything may encrypt under. Adding one is a reviewed code change; the catalog
# (registry.encrypted_fields) and the boot self-test both read this tuple.
PURPOSES = ("mfa_totp",)

# Masking (§ 25): shorter than this is fully masked — last-4 of an 8-character secret is half of it.
MASK_LAST4_MINIMUM = 16
MASKED = "••••••••"
UNREADABLE = "UNREADABLE"  # distinct from "not set" and from a masked value


class CryptoNotConfigured(Exception):
    """FIELD_ENCRYPTION_KEYS is empty: nothing can be encrypted, so the feature is unavailable."""


class DecryptionError(Exception):
    """The token did not decrypt. Never carries the plaintext or the ciphertext."""

    def __init__(self, purpose: str):
        self.purpose = purpose
        super().__init__(
            f"could not decrypt a {purpose!r} value: it was encrypted under a key that is not in "
            "FIELD_ENCRYPTION_KEYS (or under another purpose or product). Restore the key to the "
            "keyring, or have the secret re-entered. The stored value was NOT changed."
        )


def _master_keys() -> tuple[str, ...]:
    keys = tuple(k.strip() for k in getattr(settings, "FIELD_ENCRYPTION_KEYS", []) if k.strip())
    if not keys:
        raise CryptoNotConfigured(
            "FIELD_ENCRYPTION_KEYS is empty. Generate one (manage.py generate_secret --kind "
            "fernet) and set it; scripts/setup.sh does this for a development checkout."
        )
    return keys


def _derive(master: str, purpose: str) -> Fernet:
    """The per-purpose Fernet key: HKDF-SHA256(master, info=<slug>:<purpose>:v1). Cached — key
    derivation is per (master, purpose), not per call."""
    return _derive_cached(master, purpose, settings.PRODUCT_SLUG)


@functools.lru_cache(maxsize=256)
def _derive_cached(master: str, purpose: str, slug: str) -> Fernet:
    derived = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,  # the master key is already uniform random; info carries the separation
        info=f"{slug}:{purpose}:v1".encode(),
    ).derive(master.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def _check_purpose(purpose: str) -> None:
    if purpose not in PURPOSES:
        raise ValueError(f"{purpose!r} is not a registered purpose (core.crypto.PURPOSES)")


def encrypt(plaintext: str, *, purpose: str) -> str:
    """Encrypt under the NEWEST key. The token is text, for a *_ciphertext TextField."""
    _check_purpose(purpose)
    if not isinstance(plaintext, str):
        raise TypeError("encrypt() takes str plaintext")
    return _derive(_master_keys()[0], purpose).encrypt(plaintext.encode()).decode()


def _multi(purpose: str) -> MultiFernet:
    return MultiFernet([_derive(master, purpose) for master in _master_keys()])


def decrypt(token: str | bytes | memoryview, *, purpose: str) -> str:
    """Try every key, newest first. Failure RAISES: returning the input or None is how a wrong-key
    restore silently reads every secret as garbage or as "not set" (§ 25)."""
    _check_purpose(purpose)
    raw = bytes(token) if not isinstance(token, str) else token.encode()
    try:
        return _multi(purpose).decrypt(raw).decode()
    except (InvalidToken, TypeError, ValueError):
        # Deliberately NOT chained and never parameterised with the token: no plaintext, no
        # ciphertext, in no log line and no traceback.
        raise DecryptionError(purpose) from None


def rotate_token(token: str, *, purpose: str) -> str:
    """The token re-encrypted under the newest key (its plaintext never leaves this call)."""
    _check_purpose(purpose)
    try:
        return _multi(purpose).rotate(token.encode()).decode()
    except (InvalidToken, TypeError, ValueError):
        raise DecryptionError(purpose) from None


def key_fingerprints() -> tuple[str, ...]:
    """First 8 hex of SHA-256 per master key, newest first. Identifies a key in rotation output
    and /api/system/crypto/ without ever showing it."""
    return tuple(hashlib.sha256(k.encode()).hexdigest()[:8] for k in _master_keys())


def fingerprint_of(token: str, *, purpose: str) -> str | None:
    """Which keyring entry decrypts `token` (its fingerprint), or None. Fernet tokens do not name
    their key, so attribution is by trying each — exact, just O(keys)."""
    for master, fingerprint in zip(_master_keys(), key_fingerprints(), strict=True):
        try:
            _derive(master, purpose).decrypt(token.encode())
            return fingerprint
        except (InvalidToken, TypeError, ValueError):
            continue
    return None


def mask(value: str | None, *, unreadable: bool = False) -> str:
    """The § 25 masking table. `unreadable=True` is the caller's "decrypt raised" rendering."""
    if unreadable:
        return UNREADABLE
    if not value:
        return ""  # "not set" — distinct from a short secret
    if len(value) < MASK_LAST4_MINIMUM:
        return MASKED
    return f"••••{value[-4:]}"


def self_test() -> None:
    """Encrypt and decrypt a probe for every purpose. Called from CoreConfig.ready(): a process
    that cannot encrypt must refuse to start, not fall back to storing plaintext. An EMPTY keyring
    in development is not a failure (MFA simply answers 503); dbx.crypto.E001 refuses it anywhere
    production-like."""
    try:
        keys = _master_keys()
    except CryptoNotConfigured:
        return
    probe = "boot-self-test"
    for purpose in PURPOSES:
        for master in keys:
            fernet = _derive(master, purpose)
            if fernet.decrypt(fernet.encrypt(probe.encode())) != probe.encode():
                raise RuntimeError(f"crypto self-test failed for {purpose!r}")  # pragma: no cover
    logger.debug("core.crypto.self_test_ok", extra={"purposes": len(PURPOSES), "keys": len(keys)})
