"""dbx.jobs.E022 (TECH_DEBT DB-59): an outbox topic's lease outlasts its handler's worst case."""

import pytest

from core import checks
from core.jobs.retry import RetryPolicy
from core.registry import HttpPurpose, Registry
from tests.core.outbox.conftest import topic

PURPOSE = HttpPurpose(
    name="tests.partner",
    owner_module="tests",
    description="A test purpose. If it stops, only these tests notice.",
    connect_timeout=5,
    read_timeout=10,
    retry=RetryPolicy(max_attempts=3, base_seconds=2, factor=2, cap_seconds=60),
)


@pytest.fixture
def registered(monkeypatch):
    reg = Registry()
    reg.http_purposes.register(PURPOSE)
    monkeypatch.setattr("core.registry.registry", reg)
    return reg


def test_the_worst_case_counts_every_attempt_and_backoff():
    # 3 attempts × (5 + 10) s + the longest delays after attempts 1 and 2 (2 s, 4 s).
    assert checks.worst_case_seconds(PURPOSE) == 51


def test_a_lease_shorter_than_the_worst_case_is_refused(registered):
    registered.outbox_topics.register(
        topic("tests.hook", "sends", http_purpose="tests.partner", lease_seconds=60)
    )
    assert [e.id for e in checks.check_outbox_leases(None)] == ["dbx.jobs.E022"]


def test_a_lease_that_outlasts_it_passes(registered):
    registered.outbox_topics.register(
        topic("tests.hook", "sends", http_purpose="tests.partner", lease_seconds=62)
    )
    assert checks.check_outbox_leases(None) == []


def test_an_unknown_purpose_is_refused(registered):
    registered.outbox_topics.register(topic("tests.hook", "sends", http_purpose="tests.nobody"))
    assert [e.id for e in checks.check_outbox_leases(None)] == ["dbx.jobs.E022"]


def test_mail_is_checked_against_the_smtp_timeout(registered, settings):
    registered.outbox_topics.register(
        topic("tests.mail", "sends", http_purpose="smtp", lease_seconds=25)
    )
    settings.EMAIL_TIMEOUT = 10
    assert [e.id for e in checks.check_outbox_leases(None)] == ["dbx.jobs.E022"]
    settings.EMAIL_TIMEOUT = 5
    assert checks.check_outbox_leases(None) == []
    settings.EMAIL_TIMEOUT = None
    assert [e.id for e in checks.check_outbox_leases(None)] == ["dbx.jobs.E022"]


def test_a_topic_without_a_purpose_is_not_checked(registered):
    registered.outbox_topics.register(topic("tests.hook", "sends", lease_seconds=1))
    assert checks.check_outbox_leases(None) == []
