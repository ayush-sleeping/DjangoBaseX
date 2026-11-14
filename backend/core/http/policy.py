"""
What only core/http/, core/mail/ and */adapters/ may import (JOBS_AND_INTEGRATIONS.md § 18, § 27).

tests/architecture/test_outbound_http_goes_through_core_http.py refuses these imports anywhere
else. A module that adds a provider SDK appends its import name here, in the same change, and
constructs it only inside an adapter that calls core.http.guard.allows() before each call.
"""

OUTBOUND_HTTP_MODULES = (
    "httpx",
    "httpcore",
    "requests",
    "urllib.request",
    "http.client",
    "urllib3",
)
OUTBOUND_MAIL_MODULES = ("smtplib",)
OUTBOUND_SDK_MODULES: tuple[str, ...] = ()  # e.g. "stripe", "boto3": none ship with the core
