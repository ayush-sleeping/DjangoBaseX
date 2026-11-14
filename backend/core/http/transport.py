"""
The connection layer of core.http (JOBS_AND_INTEGRATIONS.md § 18).

VettingBackend is an httpcore network backend: its connect_tcp(host, port) resolves `host`, vets
every address, and dials the vetted one. httpx keeps the hostname in the URL, so the Host header,
TLS SNI and certificate verification all still use the real name; only the socket goes to the
pinned IP. Every new connection is vetted, so redirects are covered with no extra code.

PinnedTransport is httpx's own transport with its connection pool rebuilt around that backend.
httpx 0.28 has no public parameter for it, so this replaces the private `_pool` attribute; the
pyproject pin (<0.29) and tests/core/http/test_client.py::test_the_pool_dials_through_the_vetting_
backend hold that in place. Revisit both on any httpx upgrade (TECH_DEBT).

HostPoolTransport keeps one PinnedTransport per hostname: a purpose's connections to two hostnames
that share one CDN address must never share a TLS connection made for the other name.
"""

import threading

import httpcore
import httpx

from core.providers.errors import UnsafeDestination

from . import vetting


class VettingBackend(httpcore.SyncBackend):
    def __init__(self, *, vet_addresses: bool = True, resolver=None) -> None:
        self.vet_addresses = vet_addresses
        self.resolver = resolver

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        target = (
            str(vetting.vet(host, port, self.resolver or vetting.resolve))
            if self.vet_addresses
            else host
        )
        return super().connect_tcp(target, port, timeout, local_address, socket_options)


class PinnedTransport(httpx.HTTPTransport):
    def __init__(self, *, backend: VettingBackend, limits: httpx.Limits) -> None:
        super().__init__(trust_env=False, limits=limits)
        ssl_context = self._pool._ssl_context  # httpx's own verified context, kept as built
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            network_backend=backend,
        )


def validate_url(url: httpx.URL, purpose) -> None:
    """The URL shape a purpose may call, checked before any connection (and on every redirect)."""
    allowed = ("https", "http") if purpose.allow_http else ("https",)
    if url.scheme not in allowed:
        raise UnsafeDestination(f"scheme_not_allowed:{url.scheme}", host=url.host)
    if not url.host:
        raise UnsafeDestination("no_host")
    if url.userinfo:
        raise UnsafeDestination("userinfo_not_allowed", host=url.host)
    if purpose.fixed_hosts and url.host not in purpose.fixed_hosts:
        raise UnsafeDestination("host_not_in_fixed_hosts", host=url.host)


class HostPoolTransport(httpx.BaseTransport):
    """One pinned pool per hostname, created lazily, for one purpose."""

    def __init__(self, purpose, *, resolver=None, limits: httpx.Limits | None = None) -> None:
        self.purpose = purpose
        self.resolver = resolver
        self.limits = limits or httpx.Limits(max_connections=10, max_keepalive_connections=5)
        self._pools: dict[str, PinnedTransport] = {}
        self._mutex = threading.Lock()

    def _pool_for(self, host: str) -> PinnedTransport:
        with self._mutex:
            if host not in self._pools:
                backend = VettingBackend(
                    vet_addresses=self.purpose.user_controlled_urls, resolver=self.resolver
                )
                self._pools[host] = PinnedTransport(backend=backend, limits=self.limits)
            return self._pools[host]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        validate_url(request.url, self.purpose)
        return self._pool_for(request.url.host).handle_request(request)

    def close(self) -> None:
        with self._mutex:
            pools, self._pools = list(self._pools.values()), {}
        for pool in pools:
            pool.close()
