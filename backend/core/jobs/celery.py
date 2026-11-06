"""
Celery, generated from the registry (JOBS_AND_INTEGRATIONS.md § 3, § 5).

install(app) is called once, when the app finalizes. It registers one task per JobSpec
(modules never hand-write @shared_task wrappers for registered jobs), declares the queue set and
the routes from the same specs (so CELERY_TASK_CREATE_MISSING_QUEUES=False has teeth), and
connects the worker's connection hygiene. The settings themselves are in config/settings.py.
"""

from django.db import close_old_connections, connections

from core.registry import registry

from .runner import execute
from .spec import JobContext, JobSpec
from .topology import declared_queues, routes


def install(app, jobs=None) -> None:
    from kombu import Queue

    jobs = registry.jobs if jobs is None else jobs
    app.conf.task_queues = [Queue(name, routing_key=name) for name in sorted(declared_queues(jobs))]
    app.conf.task_routes = routes(jobs)
    _forget_cached_topology(app)
    for spec in jobs.specs():
        register_task(app, spec)
    _connect_worker_hygiene()


def _forget_cached_topology(app) -> None:
    """Celery caches its queue table and router on first use. Anything that published or routed
    before this install would keep the old ones, which refuse every queue but "default"."""
    # Celery internals: safe only while celery is pinned <5.7 and
    # test_install_replaces_a_topology_celery_already_cached passes.
    if "amqp" not in app.__dict__:
        return
    for name in ("queues", "default_queue", "router"):
        app.amqp.__dict__.pop(name, None)
    app.amqp.flush_routes()


def register_task(app, spec: JobSpec):
    # The keyword names here are RESERVED_KWARGS: enqueue() refuses them as job params.
    def run(self, *, trigger="schedule", idempotency_key=None, **params):
        ctx = JobContext(
            run_id=self.request.id or "",
            job_name=spec.name,
            trigger=trigger,
            idempotency_key=idempotency_key,
            params=params,
        )
        return execute(spec, ctx)

    run.__name__ = run.__qualname__ = spec.name.replace(".", "__")
    run.__doc__ = spec.description
    return app.task(
        name=spec.name,
        bind=True,
        queue=spec.queue,
        # Late ack re-delivers after a crash: right only when running twice is safe (§ 3).
        acks_late=spec.idempotent,
        reject_on_worker_lost=spec.idempotent,
        time_limit=spec.time_limit,
        soft_time_limit=spec.soft_time_limit,
        ignore_result=True,
    )(run)


def _close_connections(**kwargs) -> None:
    # A worker has no requests, so Django never closes a stale connection for it (§ 3). Never while
    # a transaction is open (a task applied in-process): closing would destroy the caller's work.
    if any(conn.in_atomic_block for conn in connections.all(initialized_only=True)):
        return
    close_old_connections()


def _connect_worker_hygiene() -> None:
    from celery.signals import task_postrun, task_prerun

    task_prerun.connect(_close_connections, weak=False, dispatch_uid="core.jobs.prerun")
    task_postrun.connect(_close_connections, weak=False, dispatch_uid="core.jobs.postrun")
