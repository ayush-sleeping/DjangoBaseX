"""
The non-production outbound guard for HTTP (JOBS_AND_INTEGRATIONS.md § 27).

Outside production (core.env.outbound_guard_active: APP_ENV is not exactly "production") only
allow-listed hosts are reachable: OUTBOUND_ALLOWLIST entries, loopback, and the product's own
hosts. Everything else is answered BY THE TRANSPORT with a synthetic 423 carrying
X-Blocked-Locally, before anything reaches the network. core.http raises it as OutboundBlocked.

There is no setting that turns the guard off: active() reads APP_ENV and nothing else.

Allow-list entries: "api.example.com" (that host), "*.example.com" (any subdomain, not the apex),
an IP literal, and a "=ro" suffix that narrows an entry to GET/HEAD/OPTIONS. A bare "*", or any
entry without a dot, is ignored: an allow-everything entry would be a switch.
"""

import logging
from urllib.parse import urlsplit

import httpx
from django.conf import settings

from core.env import outbound_guard_active

from . import vetting

logger = logging.getLogger("core.http.guard")

BLOCKED_HEADER = "X-Blocked-Locally"
READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_NAMES = frozenset({"localhost"})


def active() -> bool:
    return outbound_guard_active(settings.APP_ENV)


def _entries() -> list[tuple[str, bool]]:
    value = getattr(settings, "OUTBOUND_ALLOWLIST", None)
    if isinstance(value, str):
        value = value.split(",")
    entries = []
    for raw in value if isinstance(value, (list, tuple)) else []:
        entry = str(raw).strip().lower()
        read_only = entry.endswith("=ro")
        host = entry.removesuffix("=ro").strip()
        if "." not in host.lstrip("*.") and vetting.literal(host) is None:
            continue  # "*", "com", "": never an allow-everything entry
        entries.append((host, read_only))
    return entries


def _own_hosts() -> set[str]:
    hosts = {str(getattr(settings, "PRIMARY_DOMAIN", "") or "").lower()}
    frontend = urlsplit(str(getattr(settings, "FRONTEND_BASE_URL", "") or ""))
    hosts.add((frontend.hostname or "").lower())
    return {h for h in hosts if h}


def _matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and host != pattern[2:]
    return host == pattern


def allows(host: str, method: str) -> bool:
    """May this process reach `host` with `method`? Always True in production. Adapters whose SDK
    brings its own HTTP stack call this before each call (§ 27)."""
    if not active():
        return True
    host = (host or "").strip("[]").lower().rstrip(".")
    ip = vetting.literal(host)
    if host in LOOPBACK_NAMES or (ip is not None and ip.is_loopback):
        return True
    if host in _own_hosts():
        return True
    for pattern, read_only in _entries():
        if _matches(host, pattern):
            return not read_only or method.upper() in READ_ONLY_METHODS
    return False


class GuardTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport, purpose: str) -> None:
        self.inner = inner
        self.purpose = purpose

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if allows(request.url.host, request.method):
            return self.inner.handle_request(request)
        logger.warning(
            "core.http.blocked_locally",
            extra={
                "purpose": self.purpose,
                "host": request.url.host,
                "method": request.method,
                "app_env": settings.APP_ENV,
            },
        )
        return httpx.Response(
            423,
            headers={BLOCKED_HEADER: "1"},
            json={"error": {"code": "blocked_locally", "host": request.url.host}},
            request=request,
        )

    def close(self) -> None:
        self.inner.close()
