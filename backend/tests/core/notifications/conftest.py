"""Notification test seams: extra purposes (the registry is sealed at boot, so they are set on it
for one test), the real outbox drain, and the locmem mail outbox."""

import pytest

from core.models import NotificationPurposeState
from core.outbox.service import drain
from core.registry import NotificationPurpose, registry
from tests.factories import UserFactory

TEMPLATE = "core/email/webhook_endpoint_disabled"
CONTEXT = {"endpoint_name": "Orders", "failures": 3, "title": "Hello", "body": "Body"}


def purpose(code, **kwargs):
    base = {
        "code": code,
        "label": code,
        "owner_module": "tests",
        "description": "A test purpose.",
        "default_channels": ("email", "in_app"),
        "template": TEMPLATE,
        "preview": "core.notifications.recipients.webhook_disabled_preview",
    }
    return NotificationPurpose(**{**base, **kwargs})


@pytest.fixture
def purposes(monkeypatch):
    extra = (
        purpose("tests.plain"),
        purpose("tests.broadcast", audience=("broadcast",), default_channels=("email",)),
        purpose("tests.rollout", rollout=True),
        purpose(
            "tests.tokenrollout",
            rollout=True,
            mandatory=True,
            carries_token=True,
            default_channels=("email",),
            template="users/email/password_reset",
            preview="users.notifications.password_reset_preview",
        ),
        purpose("tests.security", mandatory=True),
    )
    for item in extra:
        monkeypatch.setitem(registry.notification_purposes._purposes, item.code, item)
    return {p.code: p for p in extra}


@pytest.fixture
def run_outbox():
    return drain


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def fire(django_capture_on_commit_callbacks, run_outbox):
    """notify() the way production runs it: commit, then the worker drains the outbox."""
    from core.notifications import notify

    def go(code, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            notify(code, **kwargs)
        run_outbox()

    return go


@pytest.fixture
def no_test_routing(db):
    def off(code):
        NotificationPurposeState.objects.update_or_create(
            purpose_code=code, defaults={"test_routing": False}
        )

    return off
