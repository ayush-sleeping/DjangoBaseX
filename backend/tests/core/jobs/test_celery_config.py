"""The Celery configuration § 3 requires, as generated from the registry (BUILD_ORDER 7.1)."""

from types import SimpleNamespace

import pytest
from celery import Celery
from django.test import override_settings
from kombu.exceptions import OperationalError

from config.celery import app
from core import checks
from core.jobs.celery import register_task
from core.jobs.topology import declared_queues
from core.registry import JobSpec, registry
from tests.core.jobs import fakes


def job_tasks():
    tasks = {name: task for name, task in app.tasks.items() if not name.startswith("celery.")}
    assert tasks, "no tasks registered: the app did not install the registry"
    return tasks


def test_every_registered_job_is_a_task():
    assert {spec.name for spec in registry.jobs.specs()} <= set(job_tasks())


def test_every_time_limit_has_a_smaller_soft_limit():
    # Every task, hand-written ones included: a hard limit with no soft one inherits the global
    # soft limit and runs for ~29 minutes (§ 3).
    for name, task in job_tasks().items():
        hard = task.time_limit or app.conf.task_time_limit
        soft = task.soft_time_limit or app.conf.task_soft_time_limit
        assert hard and soft and soft < hard, name


def test_acks_late_only_where_the_spec_is_idempotent():
    for spec in registry.jobs.specs():
        task = app.tasks[spec.name]
        assert task.acks_late is spec.idempotent, spec.name
        assert task.reject_on_worker_lost is spec.idempotent, spec.name


def test_the_queue_set_is_generated_and_closed():
    assert app.conf.task_default_queue == "default"
    assert app.conf.task_create_missing_queues is False
    assert {queue.name for queue in app.conf.task_queues} == declared_queues()


def test_publishing_to_an_undeclared_queue_raises():
    # A typo'd queue must fail at publish, not create a queue nobody consumes (§ 3).
    with pytest.raises((KeyError, OperationalError)):
        app.send_task("users.auth_cleanup", queue="bulkk")


def test_the_settings_are_the_section_3_values():
    conf = app.conf
    assert conf.task_serializer == conf.result_serializer == "json"
    assert list(conf.accept_content) == ["json"]
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_track_started is True
    assert conf.task_ignore_result is True
    assert conf.task_acks_late is False
    assert conf.task_always_eager is False
    assert conf.beat_scheduler == "django_celery_beat.schedulers:DatabaseScheduler"
    assert conf.broker_url == "memory://"  # pinned in settings_test: never a developer's Redis


def test_the_generated_task_runs_the_job_with_its_params():
    local = Celery("test", set_as_current=False)
    task = register_task(
        local,
        JobSpec(
            name="billing.count",
            func="tests.core.jobs.fakes.count_three",
            owner_module="billing",
            description="Counts to three. If it stops, the tests notice.",
        ),
    )
    fakes.CALLS.clear()
    result = task.apply(kwargs={"trigger": "enqueue", "invoice_id": 42}, task_id="run-1")
    assert result.get() == 3
    assert fakes.CALLS == [{"run_id": "run-1", "params": {"invoice_id": 42}, "trigger": "enqueue"}]


def test_a_job_that_returns_a_non_int_fails():
    local = Celery("test", set_as_current=False)
    task = register_task(
        local,
        JobSpec(
            name="billing.text",
            func="tests.core.jobs.fakes.returns_text",
            owner_module="billing",
            description="Returns text. If it stops, nothing breaks; it is a test.",
        ),
    )
    with pytest.raises(TypeError, match="returns an int"):
        task.apply(throw=True).get()


# --- dbx.jobs.E010–E015 ---------------------------------------------------------------------


def ids(errors):
    return sorted(e.id for e in errors)


def test_the_real_configuration_passes():
    assert checks.check_celery_config(None) == []


@override_settings(CELERY_BROKER_TRANSPORT_OPTIONS={"visibility_timeout": 900})
def test_e011_visibility_timeout_at_or_below_the_longest_time_limit():
    assert ids(checks.check_celery_config(None)) == ["dbx.jobs.E011"]


@override_settings(CELERY_ACCEPT_CONTENT=["json", "pickle"])
def test_e012_pickle_is_refused():
    assert ids(checks.check_celery_config(None)) == ["dbx.jobs.E012"]


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, APP_ENV="development")
def test_e013_eager_outside_tests_is_refused():
    assert ids(checks.check_celery_config(None)) == ["dbx.jobs.E013"]


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_e013_eager_in_tests_is_allowed():
    assert checks.check_celery_config(None) == []


@override_settings(APP_ENV="production", CELERY_BROKER_URL="memory://")
def test_e015_an_in_memory_broker_is_refused_in_production():
    assert ids(checks.check_celery_config(None)) == ["dbx.jobs.E015"]


@override_settings(APP_ENV="production", CELERY_BROKER_URL="redis://broker.internal:6379/1")
def test_e015_a_real_broker_passes_in_production():
    assert checks.check_celery_config(None) == []


@override_settings(CELERY_TASK_ACKS_LATE=True)
def test_e014_global_acks_late_is_refused():
    assert ids(checks.check_celery_config(None)) == ["dbx.jobs.E014"]


def test_e010_and_e014_cover_hand_written_tasks(monkeypatch):
    hand_written = SimpleNamespace(ignore_result=False, acks_late=True)
    monkeypatch.setattr(checks, "_celery_tasks", lambda: {"billing.hand_written": hand_written})
    assert ids(checks.check_celery_config(None)) == ["dbx.jobs.E010", "dbx.jobs.E014"]


@override_settings(CELERY_RESULT_BACKEND="redis://results.internal:6379/2")
def test_e010_a_shared_result_backend_allows_kept_results(monkeypatch):
    kept = SimpleNamespace(ignore_result=False, acks_late=False)
    monkeypatch.setattr(checks, "_celery_tasks", lambda: {"billing.kept": kept})
    assert checks.check_celery_config(None) == []


def test_install_replaces_a_topology_celery_already_cached():
    from core.jobs.celery import install
    from core.registry import JobRegistry

    local = Celery("test", set_as_current=False)
    local.conf.task_create_missing_queues = False
    local.conf.task_default_queue = "default"
    assert set(local.amqp.queues) == {"default"}  # cached before the registry was installed
    jobs = JobRegistry()
    jobs.register(
        JobSpec(
            name="billing.sweep",
            func="tests.core.jobs.fakes.count_three",
            owner_module="billing",
            description="Sweeps. If it stops, nothing here breaks; it is a test.",
            queue="bulk",
        )
    )
    install(local, jobs=jobs)
    assert set(local.amqp.queues) == {"default", "bulk"}
    assert local.amqp.router.route({}, "billing.sweep")["queue"].name == "bulk"


def test_install_with_an_empty_registry_installs_no_jobs():
    from core.jobs.celery import install
    from core.registry import JobRegistry

    local = Celery("test", set_as_current=False)
    local.conf.task_default_queue = "default"
    install(local, jobs=JobRegistry())
    assert {q.name for q in local.conf.task_queues} == {"default"}
    assert local.conf.task_routes == {}


@pytest.mark.django_db
def test_worker_hygiene_never_closes_a_connection_inside_a_transaction(monkeypatch):
    import core.jobs.celery as jobs_celery

    closed = []
    monkeypatch.setattr(jobs_celery, "close_old_connections", lambda: closed.append(True))
    jobs_celery._close_connections()  # pytest-django's test transaction is open
    assert closed == []


def test_worker_hygiene_closes_stale_connections_between_tasks(monkeypatch):
    import core.jobs.celery as jobs_celery

    closed = []
    monkeypatch.setattr(jobs_celery, "close_old_connections", lambda: closed.append(True))
    jobs_celery._close_connections()  # no transaction: a worker between tasks
    assert closed == [True]
