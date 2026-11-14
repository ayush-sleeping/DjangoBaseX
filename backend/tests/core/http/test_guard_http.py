"""
The non-production guard for HTTP (JOBS_AND_INTEGRATIONS.md § 27). Done when: in development a
non-allow-listed POST gets 423 and nothing leaves the machine.
"""

import httpx
import pytest

from core.http import guard
from core.http.client import SafeClient
from core.providers.errors import OutboundBlocked
from tests.core.http.conftest import purpose


@pytest.fixture
def development(settings):
    settings.APP_ENV = "development"
    settings.OUTBOUND_ALLOWLIST = ["api.allowed.example", "*.sandbox.example", "feeds.example=ro"]
    settings.PRIMARY_DOMAIN = "product.example"
    settings.FRONTEND_BASE_URL = "https://app.product.example"
    return settings


@pytest.fixture
def network():
    """The transport behind the guard: records every request that got past it."""
    seen = []
    return httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)), seen


def test_a_non_allow_listed_post_gets_423_and_never_leaves(development, network, caplog):
    inner, seen = network
    with pytest.raises(OutboundBlocked) as raised:
        SafeClient(purpose(), inner=inner).post("https://api.customer.example/hook", json={})
    assert (raised.value.status, raised.value.code) == (423, "blocked_locally")
    assert seen == []
    assert "core.http.blocked_locally" in caplog.text


def test_the_test_proves_something_with_the_guard_patched_out(development, network, monkeypatch):
    """§ 27: each guard test is shown to fail without the guard. Here: the same POST leaves."""
    monkeypatch.setattr(guard, "allows", lambda host, method: True)
    inner, seen = network
    SafeClient(purpose(), inner=inner).post("https://api.customer.example/hook", json={})
    assert len(seen) == 1


def test_the_transport_itself_answers_423(development, network):
    inner, seen = network
    response = guard.GuardTransport(inner, "tests.partner").handle_request(
        httpx.Request("POST", "https://api.customer.example/hook")
    )
    assert response.status_code == 423 and response.headers[guard.BLOCKED_HEADER] == "1"
    assert response.json()["error"]["code"] == "blocked_locally"
    assert seen == []


@pytest.mark.parametrize(
    ("host", "method", "allowed"),
    [
        ("api.allowed.example", "POST", True),
        ("x.sandbox.example", "POST", True),
        ("sandbox.example", "POST", False),  # *.x is subdomains, not the apex
        ("feeds.example", "GET", True),
        ("feeds.example", "POST", False),  # =ro
        ("localhost", "POST", True),
        ("127.0.0.1", "POST", True),
        ("::1", "POST", True),
        ("product.example", "POST", True),  # our own hosts
        ("app.product.example", "GET", True),
        ("api.customer.example", "GET", False),
        ("evil.allowed.example", "GET", False),
    ],
)
def test_the_allow_list(development, host, method, allowed):
    assert guard.allows(host, method) is allowed


def test_an_allow_everything_entry_is_ignored(development):
    development.OUTBOUND_ALLOWLIST = ["*", "*.com", "com", ""]
    assert guard.allows("api.customer.com", "GET") is False


def test_an_allow_listed_host_goes_through(development, network):
    inner, seen = network
    assert (
        SafeClient(purpose(), inner=inner).post("https://api.allowed.example/x").status_code == 200
    )
    assert len(seen) == 1


def test_a_real_upstream_423_is_not_the_guard(settings):
    settings.APP_ENV = "production"
    inner = httpx.MockTransport(lambda r: httpx.Response(423))
    assert SafeClient(purpose(), inner=inner).get("https://dav.example/").status_code == 423


@pytest.mark.parametrize("app_env", ["development", "test", "staging", "Production ", "prod", ""])
def test_the_guard_is_on_everywhere_but_production(settings, app_env):
    settings.APP_ENV = app_env
    assert guard.active() is not (app_env.strip().lower() == "production")


def test_production_reaches_anyone(settings, network):
    settings.APP_ENV = "production"
    inner, seen = network
    SafeClient(purpose(), inner=inner).post("https://api.customer.example/hook")
    assert len(seen) == 1


def test_no_setting_disables_the_guard(settings):
    """§ 27: there is no DISABLE_OUTBOUND_GUARD. Whatever a GUARD/OUTBOUND-named setting holds,
    a development box stays guarded and an unknown host stays blocked."""
    from django.conf import settings as live

    settings.APP_ENV = "development"
    names = [n for n in dir(live) if n.isupper() and ("GUARD" in n or "OUTBOUND" in n)]
    assert names, "found no guard setting at all: the scan is looking in the wrong place"
    for name in names:
        for value in (False, True, "", "off", "0", ["*"], ["*.com"], None):
            setattr(settings, name, value)
            assert guard.active() is True, name
            assert guard.allows("api.customer.example", "POST") is False, (name, value)
