"""Ops alerting test seams: a real route (data, not code), the real outbox drain, locmem mail and a
patched clock. Everything goes through notify() and the delivery log, as production does."""

from datetime import UTC, datetime

import pytest
from django.core import mail
from django.utils import timezone

from core import settings_service
from core.notifications import service
from core.outbox.service import drain

pytestmark = pytest.mark.django_db


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def route(db):
    return service.save_route(
        actor=None,
        purpose_code="core.ops_alert",
        channel="email",
        target={"addresses": ["ops@example.com"]},
    )


@pytest.fixture
def digest_route(db):
    return service.save_route(
        actor=None,
        purpose_code="core.ops_digest",
        channel="email",
        target={"addresses": ["ops@example.com"]},
    )


@pytest.fixture
def flush(django_capture_on_commit_callbacks):
    """Run `fn` the way a worker does: commit, then drain the outbox. Returns fn's result."""

    def go(fn=lambda: None):
        with django_capture_on_commit_callbacks(execute=True):
            result = fn()
        drain()
        return result

    return go


@pytest.fixture
def sent_mail():
    return lambda: [m.subject for m in mail.outbox]


@pytest.fixture
def setting():
    def put(key, value):
        settings_service.set_value(key, value)

    return put


@pytest.fixture
def at(monkeypatch):
    def freeze(moment: datetime):
        monkeypatch.setattr(timezone, "now", lambda: moment)

    return freeze
