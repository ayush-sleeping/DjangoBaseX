"""
core.http.client(purpose): the only way application code makes an outbound HTTP request
(JOBS_AND_INTEGRATIONS.md § 18).

A SafeClient is an httpx.Client built from the purpose's policy:
- its transport is GuardTransport(HostPoolTransport(...)): the non-production guard first, then
  the URL shape check, then a per-hostname pool whose every connection dials a vetted IP;
- timeouts always (the purpose's connect/read), trust_env=False (a proxy variable must not route
  around the vetting), no cookie jar, redirects only when the purpose allows them (hop limit);
- send() retries idempotent requests (or ones carrying Idempotency-Key) on transient failures with
  the purpose's RetryPolicy, honouring Retry-After; buffers the body and cuts it at
  max_response_bytes; raises OutboundBlocked for the guard's 423; and logs each attempt with
  method, host, path, status, duration and purpose. Never the query, a header value or a body.

Translating a failed call into a ProviderError is the adapter's job (core.providers.errors).
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlsplit

import httpx

from core.jobs.retry import is_retryable_status
from core.providers.errors import (
    OutboundBlocked,
    ProviderResponseError,
    UnsafeDestination,
    parse_retry_after,
)
from core.registry import registry

from .guard import BLOCKED_HEADER, GuardTransport
from .transport import HostPoolTransport

logger = logging.getLogger("core.http")

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
MAX_FANOUT_WORKERS = 16
_sleep = time.sleep  # tests replace it


def _no_cookies() -> CookieJar:
    """A jar that keeps nothing: one tenant's upstream session cookie must never ride along on
    the next tenant's request through a pooled client."""
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


class SafeClient(httpx.Client):
    def __init__(self, purpose, *, resolver=None, inner: httpx.BaseTransport | None = None):
        self.purpose = purpose
        transport = GuardTransport(
            inner if inner is not None else HostPoolTransport(purpose, resolver=resolver),
            purpose.name,
        )
        super().__init__(
            transport=transport,
            timeout=httpx.Timeout(
                connect=purpose.connect_timeout,
                read=purpose.read_timeout,
                write=purpose.read_timeout,
                pool=purpose.connect_timeout,
            ),
            follow_redirects=purpose.follow_redirects,
            max_redirects=purpose.max_redirects,
            trust_env=False,
            cookies=_no_cookies(),
        )

    def send(self, request, *, stream=False, auth=None, follow_redirects=None):
        if follow_redirects and not self.purpose.follow_redirects:
            follow_redirects = False  # a caller cannot widen the purpose's policy
        policy = self.purpose.retry
        retryable = request.method in IDEMPOTENT_METHODS or "idempotency-key" in request.headers
        attempts = policy.max_attempts if (policy is not None and retryable) else 1
        attempt = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                response = super().send(
                    request, stream=True, auth=auth, follow_redirects=follow_redirects
                )
            except UnsafeDestination:
                self._log(request, None, started, attempt, "unsafe_destination")
                raise
            except httpx.TransportError as exc:
                self._log(request, None, started, attempt, type(exc).__name__)
                delay = policy.next_delay(attempt) if attempt < attempts else None
                if delay is None:
                    raise
                _sleep(delay)
                continue
            try:
                body = self._read_capped(response)
            finally:
                response.close()
            self._log(request, response.status_code, started, attempt, "")
            if response.status_code == 423 and response.headers.get(BLOCKED_HEADER):
                raise OutboundBlocked(self.purpose.name, safe_detail=request.url.host)
            if is_retryable_status(response.status_code) and attempt < attempts:
                after = parse_retry_after(response.headers.get("Retry-After"))
                delay = policy.next_delay(attempt, after)
                if delay is not None:
                    _sleep(delay)
                    continue
            # The body is already decoded (the cap counts what we hold, so a small gzip cannot
            # inflate past it): drop the headers that would make httpx decode it again.
            headers = httpx.Headers(response.headers)
            for name in ("content-encoding", "content-length", "transfer-encoding"):
                headers.pop(name, None)
            return httpx.Response(
                response.status_code,
                headers=headers,
                content=body,
                request=request,
                extensions=response.extensions,
            )

    def _read_capped(self, response: httpx.Response) -> bytes:
        cap, chunks, size = self.purpose.max_response_bytes, [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > cap:
                raise ProviderResponseError(
                    self.purpose.name, code="response_too_large", safe_detail=f"over {cap} bytes"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _log(self, request, status, started, attempt, error) -> None:
        logger.info(
            "core.http.request",
            extra={
                "purpose": self.purpose.name,
                "method": request.method,
                "host": request.url.host,
                "path": request.url.path,  # never the query: it can carry tokens
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "attempt": attempt,
                "error": error,
            },
        )


_clients: dict[tuple[int, str], SafeClient] = {}
_clients_mutex = threading.Lock()


def client(purpose: str) -> SafeClient:
    """The process's client for a registered purpose. KeyError for an unregistered one."""
    spec = registry.http_purposes.get(purpose)
    key = (os.getpid(), purpose)  # a forked worker never reuses its parent's sockets
    with _clients_mutex:
        if key not in _clients:
            _clients[key] = SafeClient(spec)
        return _clients[key]


def close_all(**_) -> None:
    """Close every pool this process opened (worker shutdown)."""
    with _clients_mutex:
        clients = list(_clients.values())
        _clients.clear()
    for each in clients:
        each.close()


def fan_out(purpose: str, requests, *, max_workers: int = 4) -> list:
    """
    Bounded concurrency for fan-out (§ 18): `requests` is an iterable of (method, url, kwargs).
    Returns a list in the same order, each a Response or the exception it raised. Never more than
    MAX_FANOUT_WORKERS threads, however many targets.
    """
    http = client(purpose)
    workers = max(1, min(max_workers, MAX_FANOUT_WORKERS))

    def one(item):
        method, url, kwargs = item
        try:
            return http.request(method, url, **(kwargs or {}))
        except Exception as exc:  # noqa: BLE001 — returned to the caller, in order
            return exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, list(requests)))


def validate_display_url(url: str) -> str:
    """A URL that is rendered, never fetched (a logo link): https, a host, no userinfo. No DNS
    lookup, and it is never passed to client()."""
    parts = urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("a display URL is https:// with a host")
    if parts.username or parts.password:
        raise ValueError("a display URL carries no credentials")
    return url
