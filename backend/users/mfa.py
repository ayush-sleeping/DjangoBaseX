"""
TOTP and recovery-code primitives (AUTH_BLUEPRINT § 3.6, § 6.8, A16). Pure functions: no models, no
database, no requests. The models and endpoints are built on exactly this API.

A 6-digit code is only 10⁶ wide, so the verification rules are the control: ±1 time step, never a
step at or before the last one used (the replay guard), compared in constant time.
"""

import hashlib
import hmac
import secrets
import time
from datetime import datetime

import pyotp
from cryptography.fernet import Fernet
from django.conf import settings

DIGITS = 6
STEP_SECONDS = 30
DRIFT_STEPS = 1

# No 0/O, 1/I/L: a code read off paper must not be ambiguous. 31 symbols ≈ 4.95 bits each, so a
# code needs 11+ of them for 50 bits; two groups of six (≈ 59 bits) keep it easy to read aloud.
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_GROUPS, RECOVERY_GROUP_LENGTH = 2, 6


class MfaNotConfigured(Exception):
    """MFA_ENCRYPTION_KEY is empty: secrets cannot be stored, so MFA cannot be offered."""


def new_secret() -> str:
    return pyotp.random_base32()


def _fernet() -> Fernet:
    key = settings.MFA_ENCRYPTION_KEY
    if not key:
        raise MfaNotConfigured("MFA_ENCRYPTION_KEY is not set.")
    return Fernet(key)


def encrypt_secret(secret_b32: str) -> bytes:
    return _fernet().encrypt(secret_b32.encode())


def decrypt_secret(token: bytes | memoryview) -> str:
    """Accepts memoryview: BinaryField returns one on PostgreSQL. Raises
    cryptography.fernet.InvalidToken for a value encrypted under another key."""
    return _fernet().decrypt(bytes(token)).decode()


def provisioning_uri(secret_b32: str, account_email: str) -> str:
    return _totp(secret_b32).provisioning_uri(name=account_email, issuer_name=settings.MFA_ISSUER)


def verify_totp(
    secret_b32: str, code: str, last_used_timestep: int, at: datetime | None = None
) -> int | None:
    """The accepted time step, or None. The caller stores the step as the device's
    last_used_timestep, which is what makes the replay guard monotonic."""
    code = "".join(code.split())
    if len(code) != DIGITS or not (code.isascii() and code.isdigit()):
        return None

    now = at.timestamp() if at is not None else time.time()
    current = int(now) // STEP_SECONDS
    totp = _totp(secret_b32)
    accepted = None
    # Every candidate is compared, with no early return, so timing says nothing about which matched.
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        matches = hmac.compare_digest(totp.generate_otp(step), code)
        if matches and step > last_used_timestep:
            # The latest matching step: accepting an earlier one would leave the same code
            # replayable at the later step if two adjacent steps happen to share it.
            accepted = step
    return accepted


def generate_recovery_codes(count: int = 10) -> list[str]:
    codes: set[str] = set()
    while len(codes) < count:
        groups = (
            "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_GROUP_LENGTH))
            for _ in range(RECOVERY_GROUPS)
        )
        codes.add("-".join(groups))
    return list(codes)


def normalize_recovery_code(code: str) -> str:
    return code.upper().replace(" ", "").replace("-", "")


def hash_recovery_code(code: str) -> str:
    """sha256 is enough here: the codes are ~59 random bits, not human-chosen passwords."""
    return hashlib.sha256(normalize_recovery_code(code).encode()).hexdigest()


def _totp(secret_b32: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret_b32, digits=DIGITS, interval=STEP_SECONDS)
