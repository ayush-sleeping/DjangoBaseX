import pytest

from core.locks import MemoryStore, set_store
from core.registry import AT_LEAST_ONCE, AT_MOST_ONCE, OutboxTopic, Registry
from tests.core.outbox import handlers

HANDLERS = "tests.core.outbox.handlers"


def topic(name, handler, semantics=AT_MOST_ONCE, **extra):
    return OutboxTopic(
        topic=name,
        handler=f"{HANDLERS}.{handler}",
        semantics=semantics,
        owner_module="tests",
        description="A test topic. If it stops, only these tests notice.",
        **extra,
    )


@pytest.fixture
def topics():
    reg = Registry()
    for spec in (
        topic("tests.email", "sends"),
        topic("tests.webhook", "sends", AT_LEAST_ONCE),
        topic("tests.dies", "dies_mid_send"),
        topic("tests.dies_alo", "dies_mid_send", AT_LEAST_ONCE),
        topic("tests.leaky", "leaks_a_secret", AT_LEAST_ONCE),
        topic("tests.leaky_amo", "leaks_a_secret"),
        topic("tests.permanent", "permanent_error", AT_LEAST_ONCE),
        topic("tests.sms", "not_configured"),
        topic("tests.notify", "checks_suppression"),
        topic("tests.nonsense", "returns_nonsense"),
    ):
        reg.outbox_topics.register(spec)
    return reg.outbox_topics


@pytest.fixture(autouse=True)
def _fresh():
    handlers.CALLS.clear()
    set_store(MemoryStore())
    yield
    set_store(None)
