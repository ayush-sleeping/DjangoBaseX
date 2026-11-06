"""JobSpec.single_flight is enforced (JOBS_AND_INTEGRATIONS.md § 9): a second concurrent run is
recorded as skipped, not run; single_flight=False never takes the lock."""

import pytest
from celery import Celery

from config.celery import app
from core.jobs.celery import register_task
from core.locks import LockStoreUnavailable, MemoryStore, job_lock_ttl_ms, set_store, single_flight
from core.registry import JobSpec
from tests.core.jobs import fakes
from tests.core.jobs.dbs import DATABASES, runs

pytestmark = pytest.mark.django_db(databases=DATABASES)


@pytest.fixture(autouse=True)
def _setup():
    app.finalize(auto=True)  # connects the recorder, as in every real process
    fakes.CALLS.clear()
    set_store(MemoryStore())
    yield
    set_store(None)


def task(single=True):
    return register_task(
        Celery("test", set_as_current=False),
        JobSpec(
            name="billing.count",
            func="tests.core.jobs.fakes.count_three",
            owner_module="billing",
            description="A test job. If it stops, only these tests notice.",
            single_flight=single,
        ),
    )


def test_a_run_holding_nothing_runs():
    assert task().apply(task_id="free").get() == 3
    assert runs().get(task_id="free").status == "succeeded"


def test_a_concurrent_run_is_skipped_and_recorded():
    with single_flight("job:billing.count", job_lock_ttl_ms(300)):
        assert task().apply(task_id="second").get() == 0
    assert fakes.CALLS == []
    run = runs().get(task_id="second")
    assert (run.status, run.error_type, run.error_message) == ("skipped", "", "already_running")
    assert task().apply(task_id="third").get() == 3  # released: the next run goes ahead


def test_single_flight_false_never_takes_the_lock():
    with single_flight("job:billing.count", job_lock_ttl_ms(300)):
        assert task(single=False).apply(task_id="free-for-all").get() == 3


def test_a_lock_store_outage_skips_rather_than_double_runs():
    class Down:
        def acquire(self, *args):
            raise LockStoreUnavailable("refused")

    set_store(Down())
    assert task().apply(task_id="no-store").get() == 0
    assert runs().get(task_id="no-store").status == "skipped"


def test_a_skipped_run_is_not_failing_health():
    from django.utils import timezone

    from core.jobs import health

    t = task()
    with single_flight("job:billing.count", job_lock_ttl_ms(300)):
        t.apply(task_id="skip")
    spec = JobSpec(
        name="billing.count",
        func="tests.core.jobs.fakes.count_three",
        owner_module="billing",
        description="A test job. If it stops, only these tests notice.",
    )
    state = health.job_health(spec, timezone.now(), enabled=True, policy=health.queue_policy())
    assert (state.state, state.last_status) == (health.OK, "skipped")
