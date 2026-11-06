"""enqueue(): ids-only payloads, published only after commit (JOBS_AND_INTEGRATIONS.md § 4)."""

import pytest
from celery import Celery
from django.db import transaction

from config.celery import app
from core.jobs import enqueue
from core.registry import registry
from users.models import LoginAttempt


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app, "send_task", lambda name, **kwargs: calls.append({"name": name, **kwargs})
    )
    return calls


def test_outside_a_transaction_it_publishes_at_once(sent):
    enqueue("users.auth_cleanup")
    assert sent == [
        {"name": "users.auth_cleanup", "kwargs": {"trigger": "enqueue"}, "queue": "bulk"}
    ]


# Inside the normal test transaction, never transaction=True: a transactional test flushes with
# TRUNCATE, which core_activity_log's append-only trigger refuses on PostgreSQL.


@pytest.mark.django_db
def test_enqueue_inside_atomic_publishes_only_after_commit(
    sent, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with transaction.atomic():
            enqueue("users.auth_cleanup", user_id=7)
            assert sent == []  # registered, not published
    assert len(callbacks) == 1
    assert [call["kwargs"] for call in sent] == [{"trigger": "enqueue", "user_id": 7}]


@pytest.mark.django_db
def test_rollback_publishes_nothing(sent, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            enqueue("users.auth_cleanup", user_id=7)
            raise RuntimeError("roll back")
    assert callbacks == []
    assert sent == []


@pytest.mark.django_db
def test_a_broker_failure_never_breaks_the_commit(monkeypatch, django_capture_on_commit_callbacks):
    def down(*args, **kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(app, "send_task", down)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with transaction.atomic():
            row = LoginAttempt.objects.create(identifier="x@example.com", succeeded=False)
            enqueue("users.auth_cleanup")  # robust=True: logged, not raised
    assert len(callbacks) == 1  # it ran, and its failure did not escape
    assert LoginAttempt.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("value", [object(), {"id": 1}, [1, 2], 1.5])
def test_a_non_primitive_payload_is_refused(sent, value):
    with pytest.raises(TypeError, match="pass the id"):
        enqueue("users.auth_cleanup", thing=value)
    assert sent == []


def test_an_unknown_job_is_a_programming_error(sent):
    with pytest.raises(KeyError):
        enqueue("billing.no_such_job")


def test_a_real_publish_reaches_its_declared_queue():
    """No mock: over the memory:// broker, with missing queues refused. An app whose registry
    queues were never installed would refuse "bulk" here."""
    with app.connection_for_write() as conn:
        conn.default_channel.queue_purge("bulk")
        enqueue("users.auth_cleanup")
        message = conn.SimpleQueue("bulk").get(timeout=1)
    assert message.headers["task"] == "users.auth_cleanup"
    message.ack()


@pytest.mark.parametrize("reserved", ["trigger", "idempotency_key"])
def test_the_runners_own_kwargs_are_reserved(sent, reserved):
    with pytest.raises(TypeError, match="reserved"):
        enqueue("users.auth_cleanup", **{reserved: "forged"})
    assert sent == []


def test_reserved_names_match_the_generated_task():
    import inspect

    from core.jobs.celery import register_task
    from core.jobs.spec import RESERVED_KWARGS

    local = Celery("test", set_as_current=False)
    task = register_task(local, registry.jobs.get("users.auth_cleanup"))
    keyword_only = {
        name
        for name, p in inspect.signature(task.run).parameters.items()
        if p.kind is inspect.Parameter.KEYWORD_ONLY
    }
    assert keyword_only == RESERVED_KWARGS
