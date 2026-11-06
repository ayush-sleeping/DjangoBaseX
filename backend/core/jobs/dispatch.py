"""
enqueue(): the only way work goes on a queue (JOBS_AND_INTEGRATIONS.md § 4).

Payloads are primitive ids and small scalars, and inside a transaction the publish waits for the
commit, so a task never runs against a row that does not exist yet, and a rollback publishes
nothing. Raw .delay() / .apply_async() / send_task() outside core/jobs/ fails
tests/architecture/test_no_raw_dispatch.py: this helper is the one place the rule lives.
"""

from django.db import connection, transaction

from core.registry import registry

from .spec import RESERVED_KWARGS

PRIMITIVES = (int, str, bool, type(None))


def _assert_primitive(kwargs: dict) -> None:
    for key, value in kwargs.items():
        if not isinstance(value, PRIMITIVES):
            raise TypeError(
                f"enqueue kwarg {key!r} is a {type(value).__name__}: pass the id, not the object "
                "(JOBS_AND_INTEGRATIONS.md § 4)"
            )


def enqueue(name: str, /, **kwargs: int | str | bool | None) -> None:
    spec = registry.jobs.get(name)  # unknown name → KeyError, a programming error
    reserved = sorted(RESERVED_KWARGS & kwargs.keys())
    if reserved:
        raise TypeError(f"enqueue kwargs {reserved} are reserved by the job runner, not job params")
    _assert_primitive(kwargs)
    # The composition root's app: config/celery.py makes itself current. Core never imports config.
    from celery import current_app as app

    # Finalizing installs the registry's queues and routes (core.jobs.celery.install). A web process
    # never touches app.tasks, and with missing queues refused, an unfinalized app would reject
    # every queue but "default".
    app.finalize(auto=True)

    def send() -> None:
        # A named function, not functools.partial: Django logs a failed robust callback by its
        # __qualname__, which a partial does not have.
        app.send_task(name, kwargs={"trigger": "enqueue", **kwargs}, queue=spec.queue)

    if connection.in_atomic_block:
        # robust: a broker that is down never breaks the save that already committed.
        transaction.on_commit(send, robust=True)
    else:
        send()
