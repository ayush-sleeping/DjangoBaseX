"""Webhook test seams: a scripted network (core.http's transport seam, never real HTTP), a resolver
that answers public addresses, and one outbox drain."""

import importlib
import ipaddress
import os

import httpcore
import httpx
import pytest
from rest_framework.test import APIClient

from core.outbox.service import drain
from core.registry import registry
from core.webhooks import service
from rbac import services
from tests.core.webhooks import fake_handlers
from tests.factories import UserFactory

client_module = importlib.import_module("core.http.client")
PURPOSE = "webhooks.deliver"
URL = "https://hooks.example.com/in"
PUBLIC = "93.184.216.34"


@pytest.fixture(autouse=True)
def _clean():
    fake_handlers.CALLS.clear()
    yield
    client_module.close_all()


@pytest.fixture
def public_dns(monkeypatch):
    """Write-time vetting resolves every host to a public address."""
    monkeypatch.setattr(service, "resolver", lambda host, port: [ipaddress.ip_address(PUBLIC)])


class Network:
    def __init__(self):
        self.script = [httpx.Response(200, text="ok")]
        self.seen: list[httpx.Request] = []

    def answer(self, request):
        self.seen.append(request)
        item = self.script[min(len(self.seen), len(self.script)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def network(production, public_dns, monkeypatch):
    """Production (the non-production guard is off) with the transport replaced by a script."""
    net = Network()
    purpose = registry.http_purposes.get(PURPOSE)
    safe = client_module.SafeClient(purpose, inner=httpx.MockTransport(net.answer))
    monkeypatch.setitem(client_module._clients, (os.getpid(), PURPOSE), safe)
    return net


@pytest.fixture
def production(settings):
    settings.APP_ENV = "production"
    return settings


@pytest.fixture
def dialled(monkeypatch):
    """Every TCP connect httpcore would make, recorded and refused."""
    targets = []

    def connect_tcp(self, host, port, *args, **kwargs):
        targets.append((host, port))
        raise httpcore.ConnectError(f"test refused to dial {host}")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect_tcp)
    return targets


@pytest.fixture
def make_endpoint(public_dns, db):
    def build(events=("users.user.created",), url=URL, **kwargs):
        return service.create_endpoint(
            actor=None, name="Receiver", url=url, events=list(events), **kwargs
        )

    return build


@pytest.fixture
def run_outbox():
    return drain


def client_with(*codes) -> APIClient:
    user = UserFactory()
    if codes:
        slug = f"probe-{user.pk}"
        services.assign_role(
            actor=None,
            user=user,
            role=services.create_role(
                actor=None, name=slug, slug=slug, permission_codes=list(codes)
            ),
        )
    client = APIClient()
    client.force_authenticate(user=user)
    return client
