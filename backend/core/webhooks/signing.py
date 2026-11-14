"""
Signing and the headers a webhook carries (JOBS_AND_INTEGRATIONS.md § 16).

Signature = HMAC-SHA256 over "{timestamp}.{raw_body}", sent as `v1=<hex>`. During a secret rotation
the header carries one `v1=` value per live secret, comma separated.

The receiver recipe (documented in § 16 "As built"; tests execute `verify_signature` below):

    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256)
    ok = any(hmac.compare_digest(f"v1={expected.hexdigest()}", part.strip())
             for part in signature_header.split(","))
    fresh = abs(time.time() - int(timestamp)) <= 300
"""

import hashlib
import hmac
import time

from django.conf import settings

SCHEME = "v1"
DEFAULT_TOLERANCE_SECONDS = 300


def header_prefix() -> str:
    """'X-<ProductSlug>-' from PRODUCT_SLUG, never a literal: 'my-product' -> 'X-My-Product-'."""
    return "X-" + "-".join(part.capitalize() for part in settings.PRODUCT_SLUG.split("-")) + "-"


def secret_prefix() -> str:
    """'<slug_with_underscores>_whsec_': tells a human (and a secret scanner) what a value is."""
    return settings.PRODUCT_SLUG.replace("-", "_") + "_whsec_"


def header_names() -> dict[str, str]:
    prefix = header_prefix()
    return {
        "signature": prefix + "Signature",
        "timestamp": prefix + "Timestamp",
        "event": prefix + "Event",
        "delivery": prefix + "Delivery",
    }


def sign(secret: str, timestamp: int, raw_body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256)
    return f"{SCHEME}={mac.hexdigest()}"


def signature_header(secrets_in_use: list[str], timestamp: int, raw_body: bytes) -> str:
    return ",".join(sign(secret, timestamp, raw_body) for secret in secrets_in_use)


def verify_signature(
    secret: str,
    signature_header_value: str,
    timestamp_header_value: str,
    raw_body: bytes,
    *,
    tolerance: int = DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> bool:
    """The receiver's side: the signature matches one live secret AND the timestamp is fresh."""
    try:
        timestamp = int(timestamp_header_value)
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - timestamp) > tolerance:
        return False
    expected = sign(secret, timestamp, raw_body)
    return any(
        hmac.compare_digest(expected, part.strip()) for part in signature_header_value.split(",")
    )
