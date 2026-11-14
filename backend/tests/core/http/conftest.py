import ipaddress

import httpcore
import pytest

from core.registry import HttpPurpose


def purpose(**overrides) -> HttpPurpose:
    values = dict(
        name="tests.partner",
        owner_module="tests",
        description="A test purpose. If it stops, only these tests notice.",
        connect_timeout=2,
        read_timeout=3,
    )
    return HttpPurpose(**(values | overrides))


def resolver(*answers):
    """A resolver answering each call with the next list of addresses (the last one repeats)."""
    calls = []

    def resolve(host, port):
        calls.append(host)
        index = min(len(calls), len(answers)) - 1
        return [ipaddress.ip_address(a) for a in answers[index]]

    resolve.calls = calls
    return resolve


class Dialled(Exception):
    """Raised instead of opening a socket: the test records where it would have connected."""


@pytest.fixture
def dialled(monkeypatch):
    """Every TCP connect httpcore would make, recorded and refused: no test touches a network."""
    targets = []

    def connect_tcp(self, host, port, *args, **kwargs):
        targets.append((host, port))
        raise httpcore.ConnectError(f"test refused to dial {host}")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect_tcp)
    return targets


@pytest.fixture
def production(settings):
    """The guard is off only in production: SSRF must hold there on its own."""
    settings.APP_ENV = "production"
    return settings
