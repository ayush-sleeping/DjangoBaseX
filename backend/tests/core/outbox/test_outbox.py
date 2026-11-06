"""
The transactional outbox (JOBS_AND_INTEGRATIONS.md § 12; BUILD_ORDER 7.3).

Done when: killing a worker mid-send leaves the row `unknown`, not re-sent; a rolled-back
transaction leaves no outbox row. Inside the normal test transaction, never transaction=True (the
audit log's TRUNCATE trigger); the PostgreSQL concurrency proof uses its own connections.
"""

import threading
import uuid
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone

from core.models import Finding, OutboxMessage
from core.outbox import enqueue
from core.outbox.recovery import LeaseRecovery
from core.outbox.service import (
    DRAIN_JOB,
    OBJECT_TYPE,
    UNKNOWN_KIND,
    claim,
    deliver,
    drain,
    resolve_unknown,
    settle,
)
from core.registry import Registry, RegistryError
from tests.core.outbox import handlers
from tests.core.outbox.conftest import topic

pytestmark = pytest.mark.django_db


def put(topics, name="tests.email", key=None, **payload):
    with transaction.atomic():
        enqueue(
            name, dedupe_key=key or f"{name}:{uuid.uuid4().hex}", payload=payload, topics=topics
        )
    return OutboxMessage.objects.order_by("-id").first()


def expire_leases():
    OutboxMessage.objects.filter(status="leased").update(
        leased_until=timezone.now() - timedelta(seconds=1)
    )


def open_findings(kind, row):
    return Finding.objects.open().of(kind, OBJECT_TYPE, str(row.pk))


# --- Enqueue ------------------------------------------------------------------------------------


def test_enqueue_twice_is_one_row(topics):
    put(topics, key="tests.email:invoice-7:v1", invoice_id=7)
    put(topics, key="tests.email:invoice-7:v1", invoice_id=7)
    assert OutboxMessage.objects.filter(dedupe_key="tests.email:invoice-7:v1").count() == 1


def test_rollback_leaves_no_row(topics, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks() as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            enqueue("tests.email", dedupe_key="rolled-back", payload={"id": 1}, topics=topics)
            assert OutboxMessage.objects.filter(dedupe_key="rolled-back").exists()
            raise RuntimeError("the business change failed")
    assert not OutboxMessage.objects.filter(dedupe_key="rolled-back").exists()
    assert callbacks == []  # and no drain kick was published for it


def test_payload_is_ids_not_objects(topics):
    with pytest.raises(TypeError, match="pass the id"), transaction.atomic():
        enqueue("tests.email", dedupe_key="k", payload={"when": timezone.now()}, topics=topics)


def test_an_unregistered_topic_is_refused(topics):
    with pytest.raises(KeyError), transaction.atomic():
        enqueue("tests.nobody", dedupe_key="k", topics=topics)


def test_one_drain_kick_per_topic_per_transaction(topics, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks() as callbacks, transaction.atomic():
        for n in range(3):
            enqueue("tests.email", dedupe_key=f"k{n}", topics=topics)
        enqueue("tests.webhook", dedupe_key="w", topics=topics)
    assert sorted(cb.outbox_topic for cb in callbacks) == ["tests.email", "tests.webhook"]


def test_the_kick_enqueues_the_drain_job(topics, django_capture_on_commit_callbacks, monkeypatch):
    sent = []
    monkeypatch.setattr("core.jobs.enqueue", lambda name, **kw: sent.append((name, kw)))
    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        enqueue("tests.email", dedupe_key="k", topics=topics)
    assert sent == [(DRAIN_JOB, {"topic": "tests.email"})]


# --- Drain --------------------------------------------------------------------------------------


def test_a_due_message_is_sent_once(topics):
    row = put(topics, user_id=4)
    assert drain(topics=topics) == 1
    row.refresh_from_db()
    assert (row.status, row.attempts, row.result_ref) == ("sent", 1, f"provider-{row.pk}")
    assert row.sent_at and row.leased_until is None
    assert drain(topics=topics) == 0
    assert handlers.CALLS == [row.pk]


def test_the_handler_is_handed_ids_not_the_row(topics, monkeypatch):
    seen = []
    monkeypatch.setattr(handlers, "sends", lambda d: seen.append(d) or handlers.Outcome.SENT())
    row = put(topics, user_id=4)
    drain(topics=topics)
    (delivery,) = seen
    assert (delivery.id, delivery.dedupe_key, dict(delivery.payload), delivery.attempt) == (
        row.pk,
        row.dedupe_key,
        {"user_id": 4},
        1,
    )
    with pytest.raises(TypeError):
        delivery.payload["user_id"] = 5  # read-only


def test_a_message_not_yet_due_waits(topics):
    with transaction.atomic():
        enqueue("tests.email", dedupe_key="later", delay_seconds=300, topics=topics)
    assert drain(topics=topics) == 0


def test_suppressed_recipient_is_skipped_at_claim_time(topics):
    row = put(topics, "tests.notify", user_id=1, suppressed=True)
    drain(topics=topics)
    row.refresh_from_db()
    assert (row.status, row.last_error_code) == ("skipped", "recipient_suppressed")


def test_not_configured_is_skipped_not_failed(topics):
    row = put(topics, "tests.sms")
    drain(topics=topics)
    row.refresh_from_db()
    assert (row.status, row.last_error_code) == ("skipped", "not_configured")
    assert not Finding.objects.exists()


def test_provider_error_body_is_not_persisted(topics):
    row = put(topics, "tests.leaky")
    drain(topics=topics)
    row.refresh_from_db()
    assert row.status == "retry"
    assert row.last_error_code == "ConnectionError"
    assert "hunter2" not in row.last_error_message
    assert "s3cretpw" not in row.last_error_message
    assert len(row.last_error_message) <= 1000


def test_a_transient_failure_retries_with_backoff_then_dead_letters(topics):
    row = put(topics, "tests.leaky")
    for attempt in range(1, 6):
        OutboxMessage.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now())
        assert drain(topics=topics) == 1
        row.refresh_from_db()
        assert row.attempts == attempt
    # max_attempts counts every attempt, the first included: five calls, then the dead letter.
    assert row.status == "failed"
    assert len(handlers.CALLS) == 5
    assert open_findings("outbox.failed", row).count() == 1


def test_a_permanent_failure_fails_at_once(topics):
    row = put(topics, "tests.permanent")
    drain(topics=topics)
    row.refresh_from_db()
    assert (row.status, row.attempts, row.last_error_code) == ("failed", 1, "ValueError")


def test_an_at_most_once_exception_is_unknown_not_retried(topics):
    row = put(topics, "tests.leaky_amo")
    drain(topics=topics)
    row.refresh_from_db()
    assert row.status == "unknown"
    assert open_findings(UNKNOWN_KIND, row).count() == 1
    assert drain(topics=topics) == 0


def test_a_handler_that_answers_nonsense_is_unknown(topics):
    row = put(topics, "tests.nonsense")
    drain(topics=topics)
    row.refresh_from_db()
    assert (row.status, row.last_error_code) == ("unknown", "handler_returned_str")


def test_drain_honours_a_topic_and_its_batch_size(topics):
    for _ in range(3):
        put(topics, "tests.email")
    put(topics, "tests.webhook")
    assert drain(topic="tests.email", topics=topics) == 3
    assert OutboxMessage.objects.get(topic="tests.webhook").status == "pending"
    assert drain(topic="tests.nobody", topics=topics) == 0


# --- The done-when: a worker killed mid-send ----------------------------------------------------


def test_killed_worker_mid_send_leaves_unknown_and_never_resends(topics):
    row = put(topics, "tests.dies", user_id=9)
    with pytest.raises(handlers.WorkerKilled):
        drain(topics=topics)  # the process "dies" inside the handler: no result is written
    row.refresh_from_db()
    assert (row.status, row.attempts) == ("leased", 1)

    # While the lease runs, no drainer touches it; the drainer never recovers leases itself.
    assert drain(topics=topics) == 0
    expire_leases()
    assert drain(topics=topics) == 0

    report = LeaseRecovery(topics=topics).run()
    assert report.fixed == 1
    row.refresh_from_db()
    assert (row.status, row.last_error_code) == ("unknown", "lease_expired")
    finding = open_findings(UNKNOWN_KIND, row).get()
    assert finding.details["attempt"] == 1 and finding.details["locked_by"]

    # Terminal and human-owned: no drainer, no further recovery pass ever sends it again.
    assert drain(topics=topics) == 0
    assert LeaseRecovery(topics=topics).run().seen == 0
    assert handlers.CALLS == [row.pk]


def test_stale_lease_is_unknown_for_at_most_once_and_retry_for_at_least_once(topics):
    amo = put(topics, "tests.dies")
    alo = put(topics, "tests.dies_alo")
    for _ in range(2):
        with pytest.raises(handlers.WorkerKilled):
            drain(topics=topics)
    expire_leases()
    LeaseRecovery(topics=topics).run()
    amo.refresh_from_db()
    alo.refresh_from_db()
    assert amo.status == "unknown"
    assert alo.status == "retry" and alo.next_attempt_at > timezone.now() - timedelta(seconds=1)
    assert not open_findings(UNKNOWN_KIND, alo).exists()


def test_a_stale_lease_of_an_unregistered_topic_fails_closed_to_unknown(topics):
    row = put(topics, "tests.dies")
    with pytest.raises(handlers.WorkerKilled):
        drain(topics=topics)
    OutboxMessage.objects.filter(pk=row.pk).update(topic="tests.gone")
    expire_leases()
    LeaseRecovery(topics=topics).run()
    row.refresh_from_db()
    assert row.status == "unknown"


def test_a_late_sent_under_the_same_token_settles_an_unknown(topics):
    row = put(topics, "tests.email")
    claimed = claim(["tests.email"], topics=topics)
    expire_leases()
    LeaseRecovery(topics=topics).run()
    assert open_findings(UNKNOWN_KIND, row).count() == 1
    # The "dead" worker was only slow: its SENT answers the very question the finding asked.
    assert settle(claimed, deliver(claimed, topics=topics), topics=topics) == "sent"
    row.refresh_from_db()
    assert row.status == "sent"
    assert not open_findings(UNKNOWN_KIND, row).exists()
    assert Finding.objects.get(object_id=str(row.pk)).resolution == "auto_cleared"


def test_any_other_late_result_is_dropped(topics, caplog):
    row = put(topics, "tests.email")
    claimed = claim(["tests.email"], topics=topics)
    expire_leases()
    LeaseRecovery(topics=topics).run()
    late = handlers.Outcome.FAILED("too_late")
    assert settle(claimed, late, topics=topics) == "lease_lost"
    row.refresh_from_db()
    assert row.status == "unknown"
    assert "core.outbox.late_result_dropped" in caplog.text


def test_a_result_for_a_reclaimed_row_is_dropped(topics):
    row = put(topics, "tests.webhook")
    first = claim(["tests.webhook"], topics=topics)
    expire_leases()
    LeaseRecovery(topics=topics).run()
    OutboxMessage.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now())
    second = claim(["tests.webhook"], topics=topics)
    assert first.token != second.token
    assert settle(first, handlers.Outcome.SENT("old"), topics=topics) == "lease_lost"
    assert settle(second, handlers.Outcome.SENT("new"), topics=topics) == "sent"
    row.refresh_from_db()
    assert (row.result_ref, row.attempts) == ("new", 2)


# --- A human resolves an unknown ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "status", "resolution"),
    [("mark_sent", "sent", "marked_sent"), ("resend", "retry", "resent")],
)
def test_a_human_resolves_an_unknown(topics, action, status, resolution):
    row = put(topics, "tests.leaky_amo")
    drain(topics=topics)
    assert resolve_unknown(row.pk, action, note="checked the provider log")
    row.refresh_from_db()
    assert row.status == status
    finding = Finding.objects.get(object_id=str(row.pk))
    assert (finding.resolution, finding.resolution_note) == (resolution, "checked the provider log")
    assert not resolve_unknown(row.pk, action)  # no longer unknown
    if action == "resend":
        assert row.max_attempts == row.attempts + 1  # exactly one more, deliberate attempt


# --- Registration -------------------------------------------------------------------------------


def test_a_topic_without_semantics_is_refused():
    with pytest.raises(RegistryError, match="dbx.jobs.E030"):
        Registry().outbox_topics.register(topic("tests.x", "sends", semantics=""))


def test_the_check_refuses_a_handler_that_does_not_import(monkeypatch):
    from core import checks

    reg = Registry()
    reg.outbox_topics.register(topic("tests.x", "no_such_handler"))
    monkeypatch.setattr("core.registry.registry", reg)
    errors = checks.check_outbox_topics(None)
    assert [e.id for e in errors] == ["dbx.jobs.E030"]


def test_core_registers_its_outbox_jobs_and_kinds():
    from core.registry import registry

    assert {"core.outbox_drain", "core.outbox_recover"} <= {s.name for s in registry.jobs.specs()}
    assert registry.jobs.get("core.outbox_drain").queue == "outbox"
    assert registry.jobs.get("core.outbox_drain").single_flight is False
    assert registry.jobs.get("core.outbox_recover").single_flight is True
    assert {"outbox.unknown", "outbox.failed", "core.outbox_recover.gave_up"} <= {
        k.kind for k in registry.finding_kinds.kinds()
    }
    assert "outbox" in {d.key for d in registry.doctors.doctors()}


def test_the_drain_job_runs_through_the_registry(monkeypatch, topics):
    from core.jobs.spec import JobContext
    from core.outbox import service

    monkeypatch.setattr(service, "registry", type("R", (), {"outbox_topics": topics})())
    put(topics, "tests.email")
    assert service.drain_job(JobContext(run_id="r", job_name=DRAIN_JOB)) == 1


def test_the_doctor_names_a_stuck_and_an_unrecovered_outbox(topics):
    from core.outbox.doctor import outbox_doctor

    assert [f.code for f in outbox_doctor()] == []
    old = timezone.now() - timedelta(hours=1)
    stuck = put(topics, "tests.email")
    OutboxMessage.objects.filter(pk=stuck.pk).update(next_attempt_at=old)
    leased = put(topics, "tests.webhook")
    OutboxMessage.objects.filter(pk=leased.pk).update(status="leased", leased_until=old)
    codes = {f.code: f.subject for f in outbox_doctor()}
    # tests.* topics are not in the global registry: unsendable as well as stuck.
    assert codes["outbox.stuck"] == "tests.email"
    assert codes["outbox.unregistered_topic"] in {"tests.email", "tests.webhook"}
    assert codes["outbox.recovery_stalled"] == "core.outbox_recover"


# --- PostgreSQL: two drainers never claim the same row -----------------------------------------


def _in_thread(fn):
    """Run fn on a fresh thread, so on its own autocommit connection, outside the test's
    transaction. Its connection is closed before the thread ends."""
    result, errors = [], []

    def target():
        try:
            result.append(fn())
        except BaseException as exc:  # noqa: BLE001 — re-raised on the test thread
            errors.append(exc)
        finally:
            connection.close()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=60)
    if errors:
        raise errors[0]
    return result[0]


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="SKIP LOCKED needs PostgreSQL; on SQLite select_for_update is a no-op (ADR-0005)",
)
def test_two_drainers_never_claim_the_same_row():
    reg = Registry()
    reg.outbox_topics.register(topic("tests.concurrent", "sends"))
    topics = reg.outbox_topics
    name, rows, workers = f"tests.concurrent.{uuid.uuid4().hex[:8]}", 200, 4
    reg_name = "tests.concurrent"

    def seed():
        now = timezone.now()
        OutboxMessage.objects.bulk_create(
            OutboxMessage(
                topic=reg_name,
                dedupe_key=f"{name}:{n}",
                max_attempts=5,
                next_attempt_at=now,
            )
            for n in range(rows)
        )

    def cleanup():
        OutboxMessage.objects.filter(dedupe_key__startswith=f"{name}:").delete()

    _in_thread(seed)
    try:
        barrier = threading.Barrier(workers)
        claimed: list[list[int]] = [[] for _ in range(workers)]
        failures: list[BaseException] = []

        def drainer(index):
            try:
                barrier.wait(timeout=30)
                while (got := claim([reg_name], topics=topics)) is not None:
                    claimed[index].append(got.id)
            except BaseException as exc:  # noqa: BLE001
                failures.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=drainer, args=(i,)) for i in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert not failures, failures
        every = [pk for ids in claimed for pk in ids]
        assert len(every) == rows, "some rows were never claimed"
        assert len(set(every)) == rows, "a row was claimed twice"
        assert sum(1 for ids in claimed if ids) > 1, "only one drainer claimed: no concurrency"
    finally:
        _in_thread(cleanup)


# --- Review fixes -------------------------------------------------------------------------------


def test_a_resend_is_exactly_one_more_attempt(topics, monkeypatch):
    row = put(topics, "tests.webhook")  # at_least_once: a RETRY would normally back off
    monkeypatch.setattr(handlers, "sends", lambda d: handlers.Outcome.UNKNOWN({"why": "timeout"}))
    drain(topics=topics)
    row.refresh_from_db()
    assert row.status == "unknown"
    assert resolve_unknown(row.pk, "resend")
    monkeypatch.setattr(handlers, "sends", lambda d: handlers.Outcome.RETRY(code="still_down"))
    assert drain(topics=topics) == 1
    row.refresh_from_db()
    assert (row.status, row.attempts, row.max_attempts) == ("failed", 2, 2)
    assert drain(topics=topics) == 0
    assert open_findings("outbox.failed", row).count() == 1


def test_recovery_honours_the_rows_cap_after_a_resend(topics, monkeypatch):
    row = put(topics, "tests.dies_alo")
    OutboxMessage.objects.filter(pk=row.pk).update(status="unknown", attempts=1)
    assert resolve_unknown(row.pk, "resend")
    with pytest.raises(handlers.WorkerKilled):
        drain(topics=topics)
    expire_leases()
    LeaseRecovery(topics=topics).run()
    row.refresh_from_db()
    assert (row.status, row.attempts, row.max_attempts) == ("failed", 2, 2)


def test_two_claimers_reading_the_same_row_stamp_it_once(topics, monkeypatch):
    """SQLite ignores FOR UPDATE: the stamp itself must be a compare-and-set."""
    from core.outbox import service

    first_row, second_row = put(topics, "tests.email"), put(topics, "tests.email")
    stale = service._candidate(["tests.email"], timezone.now(), [])  # claimer B reads first_row
    assert stale.pk == first_row.pk
    a = claim(["tests.email"], topics=topics)  # claimer A reads and stamps it
    assert a.id == first_row.pk

    real, served = service._candidate, []

    def same_read_once(names, now, exclude):
        if not served:
            served.append(True)
            return stale  # B's racing read of a row A already stamped
        return real(names, now, exclude)

    monkeypatch.setattr(service, "_candidate", same_read_once)
    b = claim(["tests.email"], topics=topics)
    assert b.id == second_row.pk  # lost the race on the first row, moved on to the next
    first_row.refresh_from_db()
    assert (first_row.locked_by, first_row.attempts) == (a.token, 1)


def test_a_lost_stamp_race_with_nothing_else_due_claims_nothing(topics, monkeypatch):
    from core.outbox import service

    row = put(topics, "tests.email")
    stale = service._candidate(["tests.email"], timezone.now(), [])
    claim(["tests.email"], topics=topics)
    monkeypatch.setattr(
        service, "_candidate", lambda names, now, exclude: None if exclude else stale
    )
    assert claim(["tests.email"], topics=topics) is None
    row.refresh_from_db()
    assert row.attempts == 1


def test_a_late_sent_settles_a_row_recovery_dead_lettered(topics):
    row = put(topics, "tests.webhook")
    claimed = claim(["tests.webhook"], topics=topics)
    OutboxMessage.objects.filter(pk=row.pk).update(max_attempts=1)  # recovery finds it spent
    expire_leases()
    LeaseRecovery(topics=topics).run()
    row.refresh_from_db()
    assert row.status == "failed"
    assert open_findings("outbox.failed", row).count() == 1
    assert settle(claimed, handlers.Outcome.SENT("late"), topics=topics) == "sent"
    row.refresh_from_db()
    assert (row.status, row.result_ref) == ("sent", "late")
    assert not Finding.objects.open().filter(object_id=str(row.pk)).exists()


def test_evidence_is_flat_primitives_checked_in_the_handler():
    with pytest.raises(TypeError, match="evidence"):
        handlers.Outcome.UNKNOWN({"response": {"nested": 1}})
    with pytest.raises(TypeError, match="evidence"):
        handlers.Outcome.UNKNOWN({"when": timezone.now()})


def test_evidence_is_scrubbed_before_a_human_reads_it(topics, monkeypatch):
    row = put(topics, "tests.email")
    monkeypatch.setattr(
        handlers,
        "sends",
        lambda d: handlers.Outcome.UNKNOWN(
            {"body": "timeout after send, password=hunter2", "n": 3}
        ),
    )
    drain(topics=topics)
    evidence = open_findings(UNKNOWN_KIND, row).get().details["evidence"]
    assert "hunter2" not in evidence["body"] and evidence["n"] == 3
