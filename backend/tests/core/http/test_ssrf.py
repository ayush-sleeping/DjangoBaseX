"""
Address safety (JOBS_AND_INTEGRATIONS.md § 18). Done when: a request to a private address is
refused BEFORE connecting. Every test runs with APP_ENV=production, so it is the vetting, not the
non-production guard, doing the refusing.
"""

import ipaddress
import socket

import httpcore
import httpx
import pytest

from core.http import vetting
from core.http.client import SafeClient
from core.http.transport import VettingBackend, validate_url
from core.providers.errors import UnsafeDestination
from tests.core.http.conftest import purpose, resolver

pytestmark = pytest.mark.usefixtures("production")

REFUSED = [
    "127.0.0.1",  # loopback
    "127.8.9.10",
    "::1",
    "0.0.0.0",  # unspecified
    "::",
    "10.0.0.1",  # RFC 1918
    "172.16.5.4",
    "192.168.1.1",
    "169.254.169.254",  # link-local: the cloud metadata service
    "fe80::1",
    "100.64.0.1",  # CGNAT
    "198.18.0.1",  # benchmarking
    "192.0.2.10",  # documentation
    "224.0.0.1",  # multicast
    "ff02::1",
    "240.0.0.1",  # reserved
    "fc00::1",  # unique local
    "::ffff:10.0.0.1",  # IPv4-mapped private
    "::ffff:127.0.0.1",
    "64:ff9b::a00:1",  # NAT64 of 10.0.0.1
    "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
    "2002:a00:1::",  # 6to4 of 10.0.0.1
    "2002:7f00:1::1",  # 6to4 of 127.0.0.1
    "2001:0:4136:e378:8000:63bf:f5ff:fffe",  # Teredo, client 10.0.0.1
    "::a00:1",  # IPv4-compatible 10.0.0.1
]
PUBLIC = ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"]


@pytest.mark.parametrize("address", REFUSED)
def test_non_public_addresses_are_refused(address):
    assert not vetting.is_safe(ipaddress.ip_address(address))
    with pytest.raises(UnsafeDestination):
        vetting.vet(address, 443)


@pytest.mark.parametrize("address", PUBLIC)
def test_public_addresses_pass(address):
    assert vetting.is_safe(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", REFUSED)
def test_a_private_address_is_refused_before_connecting(address, dialled):
    """The done-when, through the real client: no socket is ever dialled."""
    http = SafeClient(purpose(), resolver=resolver([address]))
    with pytest.raises(UnsafeDestination):
        http.get("https://partner.example/hook")
    with pytest.raises(UnsafeDestination):
        http.post(f"https://[{address}]/" if ":" in address else f"https://{address}/")
    assert dialled == []


def test_a_hostname_with_one_public_and_one_private_record_is_refused(dialled):
    http = SafeClient(purpose(), resolver=resolver(["1.1.1.1", "10.0.0.1"]))
    with pytest.raises(UnsafeDestination, match="non_public_address"):
        http.get("https://partner.example/")
    assert dialled == []


def test_resolution_failure_is_refused(dialled, monkeypatch):
    def fails(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fails)
    with pytest.raises(UnsafeDestination, match="resolution_failed"):
        SafeClient(purpose()).get("https://does-not-resolve.example/")
    assert dialled == []


def test_an_empty_answer_is_refused():
    with pytest.raises(UnsafeDestination, match="resolution_failed"):
        vetting.vet("partner.example", 443, resolver=lambda host, port: [])


def test_localhost_is_refused_with_the_real_resolver(monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("a socket was opened")

    monkeypatch.setattr(socket, "create_connection", never)
    with pytest.raises(UnsafeDestination):
        SafeClient(purpose()).get("https://localhost/")


def test_connection_goes_to_the_pinned_ip(dialled):
    """A resolver that answers public, then private (rebinding): the address that passed the check
    is the address dialled, and nothing resolves the name a second time."""
    rebinding = resolver(["1.1.1.1"], ["10.0.0.1"])
    with pytest.raises(httpx.ConnectError):
        SafeClient(purpose(), resolver=rebinding).get("https://partner.example/")
    assert dialled == [("1.1.1.1", 443)]
    assert rebinding.calls == ["partner.example"]


def test_the_backend_vets_then_dials(dialled):
    backend = VettingBackend(resolver=resolver(["8.8.8.8"]))
    with pytest.raises(httpcore.ConnectError):
        backend.connect_tcp("partner.example", 443)
    assert dialled == [("8.8.8.8", 443)]


def test_userinfo_is_refused():
    with pytest.raises(UnsafeDestination, match="userinfo"):
        validate_url(httpx.URL("https://user:pass@partner.example/"), purpose())


@pytest.mark.parametrize("url", ["http://partner.example/", "ftp://partner.example/"])
def test_only_https_unless_the_purpose_allows_http(url):
    with pytest.raises(UnsafeDestination, match="scheme"):
        validate_url(httpx.URL(url), purpose())
    if url.startswith("http:"):
        validate_url(httpx.URL(url), purpose(allow_http=True))


def test_fixed_hosts_refuse_any_other_host(dialled):
    fixed = purpose(user_controlled_urls=False, fixed_hosts=("api.partner.example",))
    with pytest.raises(UnsafeDestination, match="fixed_hosts"):
        SafeClient(fixed).get("https://other.example/")
    assert dialled == []


def test_redirect_is_not_followed():
    hops = []

    def answer(request):
        hops.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest"})

    http = SafeClient(purpose(), inner=httpx.MockTransport(answer))
    response = http.get("https://partner.example/", follow_redirects=True)
    assert response.status_code == 302
    assert hops == ["https://partner.example/"]


def test_a_followed_redirect_is_revalidated_on_every_hop(dialled):
    follows = purpose(follow_redirects=True, revalidate_redirects=True)
    hops = []

    class Redirecting(httpx.BaseTransport):
        def handle_request(self, request):
            validate_url(request.url, follows)
            hops.append(request.url.host)
            return httpx.Response(302, headers={"Location": "http://partner.example/insecure"})

    with pytest.raises(UnsafeDestination, match="scheme"):
        SafeClient(follows, inner=Redirecting()).get("https://partner.example/")
    assert hops == ["partner.example"]
