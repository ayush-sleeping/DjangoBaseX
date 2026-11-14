"""core.http's behaviour (JOBS_AND_INTEGRATIONS.md § 18): timeouts, retries that honour
Retry-After, the size cap, no cookie jar, no proxy variables, redaction, per-host pinned pools."""

import gzip
import importlib
import logging

import httpx
import pytest

from core.http.client import SafeClient, fan_out, validate_display_url
from core.http.transport import HostPoolTransport, PinnedTransport, VettingBackend
from core.jobs.retry import RetryPolicy
from core.providers.errors import ProviderResponseError
from core.registry import Registry
from tests.core.http.conftest import purpose

client_module = importlib.import_module("core.http.client")
pytestmark = pytest.mark.usefixtures("production")
RETRY = RetryPolicy(max_attempts=3, base_seconds=1, factor=2, cap_seconds=30)


@pytest.fixture
def slept(monkeypatch):
    delays = []
    monkeypatch.setattr(client_module, "_sleep", delays.append)
    return delays


def scripted(*responses):
    """A transport answering with each response in turn; records every request."""
    seen = []

    def answer(request):
        seen.append(request)
        item = responses[min(len(seen), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(answer), seen


def test_every_client_has_timeouts_and_no_proxy_variables():
    http = SafeClient(purpose(connect_timeout=2, read_timeout=7))
    assert (http.timeout.connect, http.timeout.read) == (2, 7)
    assert http.trust_env is False


def test_a_get_is_retried_and_retry_after_is_honoured(slept):
    inner, seen = scripted(
        httpx.Response(503, headers={"Retry-After": "4"}),
        httpx.Response(429, headers={"Retry-After": "120"}),
        httpx.Response(200, text="ok"),
    )
    response = SafeClient(purpose(retry=RETRY), inner=inner).get("https://partner.example/")
    assert (response.status_code, response.text, len(seen)) == (200, "ok", 3)
    assert slept == [4, 30]  # the second Retry-After is capped at the policy's cap


def test_retries_stop_at_max_attempts_and_return_the_last_answer(slept):
    inner, seen = scripted(httpx.Response(503))
    response = SafeClient(purpose(retry=RETRY), inner=inner).get("https://partner.example/")
    assert (response.status_code, len(seen), len(slept)) == (503, 3, 2)


def test_a_post_is_not_retried_unless_it_carries_an_idempotency_key(slept):
    inner, seen = scripted(httpx.Response(503))
    http = SafeClient(purpose(retry=RETRY), inner=inner)
    http.post("https://partner.example/", json={})
    assert len(seen) == 1
    http.post("https://partner.example/", json={}, headers={"Idempotency-Key": "k-1"})
    assert len(seen) == 4


def test_a_transport_error_is_retried_then_raised(slept):
    inner, seen = scripted(httpx.ConnectError("refused"))
    with pytest.raises(httpx.ConnectError):
        SafeClient(purpose(retry=RETRY), inner=inner).get("https://partner.example/")
    assert len(seen) == 3


def test_without_a_policy_there_is_one_attempt(slept):
    inner, seen = scripted(httpx.Response(503))
    SafeClient(purpose(), inner=inner).get("https://partner.example/")
    assert (len(seen), slept) == (1, [])


def test_a_400_is_never_retried(slept):
    inner, seen = scripted(httpx.Response(400))
    SafeClient(purpose(retry=RETRY), inner=inner).get("https://partner.example/")
    assert len(seen) == 1


def test_the_body_is_cut_at_the_size_cap():
    inner, _ = scripted(httpx.Response(200, content=b"x" * 101))
    with pytest.raises(ProviderResponseError, match="response_too_large"):
        SafeClient(purpose(max_response_bytes=100), inner=inner).get("https://partner.example/")
    inner, _ = scripted(httpx.Response(200, content=b"x" * 100))
    assert (
        len(
            SafeClient(purpose(max_response_bytes=100), inner=inner)
            .get("https://partner.example/")
            .content
        )
        == 100
    )


def test_a_small_gzip_cannot_inflate_past_the_cap():
    bomb = gzip.compress(b"\0" * 1_000_000)  # about 1 KB on the wire
    inner, _ = scripted(httpx.Response(200, content=bomb, headers={"Content-Encoding": "gzip"}))
    with pytest.raises(ProviderResponseError, match="response_too_large"):
        SafeClient(purpose(max_response_bytes=10_000), inner=inner).get("https://partner.example/")


def test_a_decoded_body_is_not_decoded_twice():
    body = gzip.compress(b'{"ok": true}')
    inner, _ = scripted(httpx.Response(200, content=body, headers={"Content-Encoding": "gzip"}))
    assert SafeClient(purpose(), inner=inner).get("https://partner.example/").json() == {"ok": True}


def test_no_cookie_rides_along_on_the_next_request():
    inner, seen = scripted(
        httpx.Response(200, headers={"Set-Cookie": "session=tenant-a; Path=/"}),
        httpx.Response(200),
    )
    http = SafeClient(purpose(), inner=inner)
    http.get("https://partner.example/a")
    http.get("https://partner.example/b")
    assert "cookie" not in seen[1].headers


def test_logs_name_the_path_never_the_query_or_headers(caplog):
    inner, _ = scripted(httpx.Response(200))
    with caplog.at_level(logging.INFO, logger="core.http"):
        SafeClient(purpose(), inner=inner).get(
            "https://partner.example/v1/items?token=s3cret", headers={"Authorization": "Bearer abc"}
        )
    (record,) = [r for r in caplog.records if r.name == "core.http"]
    assert (record.purpose, record.method, record.host, record.path, record.status) == (
        "tests.partner",
        "GET",
        "partner.example",
        "/v1/items",
        200,
    )
    assert "s3cret" not in str(record.__dict__) and "Bearer" not in str(record.__dict__)


def test_the_pool_dials_through_the_vetting_backend():
    """Pins the private-attribute swap (httpx <0.29). If this fails after an upgrade, the IP
    pinning silently stopped: fix core/http/transport.py before anything else."""
    import httpcore

    transport = PinnedTransport(backend=VettingBackend(), limits=httpx.Limits())
    assert isinstance(transport._pool, httpcore.ConnectionPool)
    assert isinstance(transport._pool._network_backend, VettingBackend)
    assert transport._pool._ssl_context is not None
    assert httpx.__version__.startswith("0.28.")


def test_each_hostname_gets_its_own_pool():
    pools = HostPoolTransport(purpose())
    assert pools._pool_for("a.example") is pools._pool_for("a.example")
    assert pools._pool_for("a.example") is not pools._pool_for("b.example")
    pools.close()


def test_fixed_host_purposes_do_not_vet_dns():
    pools = HostPoolTransport(purpose(user_controlled_urls=False, fixed_hosts=("api.example.com",)))
    assert pools._pool_for("api.example.com")._pool._network_backend.vet_addresses is False


def test_client_is_cached_per_purpose_and_refuses_unknown_ones(monkeypatch):
    reg = Registry()
    reg.http_purposes.register(purpose())
    monkeypatch.setattr(client_module, "registry", reg)
    monkeypatch.setattr(client_module, "_clients", {})
    assert client_module.client("tests.partner") is client_module.client("tests.partner")
    with pytest.raises(KeyError):
        client_module.client("tests.nobody")
    client_module.close_all()
    assert client_module._clients == {}


def test_fan_out_keeps_order_and_returns_errors(monkeypatch):
    def answer(request):
        if request.url.path == "/boom":
            raise httpx.ConnectError("down")
        return httpx.Response(200, text=request.url.path)

    http = SafeClient(purpose(), inner=httpx.MockTransport(answer))
    monkeypatch.setattr(client_module, "client", lambda name: http)
    results = fan_out(
        "tests.partner",
        [("GET", f"https://p.example/{n}", None) for n in "ab"]
        + [("GET", "https://p.example/boom", None)],
        max_workers=500,
    )
    assert [r.text for r in results[:2]] == ["/a", "/b"]
    assert isinstance(results[2], httpx.ConnectError)


def test_a_display_url_is_https_with_a_host_and_no_credentials():
    assert validate_display_url("https://cdn.example/logo.png")
    for bad in (
        "http://cdn.example/x",
        "https:///x",
        "https://u:p@cdn.example/",
        "",
        "javascript:x",
    ):
        with pytest.raises(ValueError):
            validate_display_url(bad)
