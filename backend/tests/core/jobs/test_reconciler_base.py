"""The Reconciler base (JOBS_AND_INTEGRATIONS.md § 11): per-row commits, a reported cap, drift that
mutates nothing, convergence that clears, a cursor in core_job_state. Exercised on outbox rows,
the one core model with a transient state."""

import uuid

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone

from core.jobs.reconciler import Reconciler, Result, run_registered
from core.jobs.spec import JobContext
from core.models import Finding, JobState, OutboxMessage

pytestmark = pytest.mark.django_db
KIND = "core.outbox_recover.gave_up"  # registered by core with its reconciler


def rows(n):
    now = timezone.now()
    return [
        OutboxMessage.objects.create(
            topic="tests.recon", dedupe_key=uuid.uuid4().hex, max_attempts=5, next_attempt_at=now
        )
        for _ in range(n)
    ]


class MarkSent(Reconciler):
    name = "tests.mark_sent"
    batch_size = 50

    def queryset(self):
        return OutboxMessage.objects.filter(topic="tests.recon", status="pending")

    def reconcile(self, obj):
        obj.status = "sent"
        obj.save(update_fields=["status"])
        return Result.fixed()


def test_each_row_is_reconciled_and_committed():
    rows(3)
    report = MarkSent().run()
    assert (report.seen, report.fixed, report.capped) == (3, 3, False)
    assert set(OutboxMessage.objects.values_list("status", flat=True)) == {"sent"}


def test_soft_time_limit_banks_progress():
    done = []

    class Interrupted(MarkSent):
        def reconcile(self, obj):
            if len(done) == 2:
                raise SoftTimeLimitExceeded()
            done.append(obj.pk)
            return super().reconcile(obj)

    created = rows(4)
    report = Interrupted().run()
    assert report.stopped_early and report.fixed == 2
    statuses = dict(OutboxMessage.objects.values_list("pk", "status"))
    assert [statuses[r.pk] for r in created] == ["sent", "sent", "pending", "pending"]


def test_cap_is_reported_not_silent(caplog):
    rows(5)

    class Small(MarkSent):
        batch_size = 2

    report = Small().run()
    assert (report.seen, report.capped, report.remaining) == (2, True, 3)
    assert "core.reconciler.capped" in caplog.text


def test_exists_and_differs_mutates_nothing():
    class Differs(MarkSent):
        def reconcile(self, obj):
            obj.status = "failed"  # a careless subclass "fixes" it anyway
            obj.save(update_fields=["status"])
            return Result.drift(KIND, {"provider_says": "exists, different total"})

    (row,) = rows(1)
    report = Differs().run()
    assert report.drift == 1
    row.refresh_from_db()
    assert row.status == "pending"  # the drift transaction was rolled back
    finding = Finding.objects.open().get(kind=KIND)
    assert finding.details == {"provider_says": "exists, different total"}
    Differs().run()
    finding.refresh_from_db()
    assert finding.occurrences == 2  # touched, not duplicated


def test_convergence_clears_the_finding():
    (row,) = rows(1)

    class Drifts(MarkSent):
        kinds = (KIND,)

        def reconcile(self, obj):
            return Result.drift(KIND)

    class Converged(MarkSent):
        kinds = (KIND,)

    Drifts().run()
    assert Finding.objects.open().filter(kind=KIND).count() == 1
    Converged().run()
    assert not Finding.objects.open().filter(kind=KIND).exists()
    assert Finding.objects.get(kind=KIND).resolution == "auto_cleared"


def test_skip_mutates_nothing_and_says_why(caplog):
    class Unreachable(MarkSent):
        def reconcile(self, obj):
            return Result.skip("provider_unreachable")

    rows(2)
    assert Unreachable().run().skipped == 2
    assert set(OutboxMessage.objects.values_list("status", flat=True)) == {"pending"}


def test_a_resumable_reconciler_keeps_its_cursor_in_the_database():
    class Walk(MarkSent):
        name = "tests.walk"
        resumable = True
        batch_size = 2

        def queryset(self):
            return OutboxMessage.objects.filter(topic="tests.recon")

        def reconcile(self, obj):
            return Result.unchanged()

    created = rows(3)
    assert Walk().run().seen == 2
    assert JobState.objects.get(name="tests.walk").cursor == {"after": created[1].pk}
    assert Walk().run().seen == 1  # resumed after the cursor
    state = JobState.objects.get(name="tests.walk")
    assert state.cursor is None and state.last_success_at  # a full pass: start over next time


def test_give_up_records_a_finding():
    (row,) = rows(1)

    class GivesUp(MarkSent):
        name = "core.outbox_recover"

    GivesUp().give_up(row, "provider returned 404 three times")
    assert Finding.objects.open().get(kind=KIND).details == {
        "reason": "provider returned 404 three times"
    }


def test_registered_reconcilers_run_by_job_name():
    assert run_registered(JobContext(run_id="r", job_name="core.outbox_recover")) == 0
