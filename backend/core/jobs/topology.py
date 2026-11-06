"""The queues the registry declares (JOBS_AND_INTEGRATIONS.md § 5). A queue exists because a spec
names it; `default` always exists, because it is CELERY_TASK_DEFAULT_QUEUE."""

from django.conf import settings

from core.registry import registry


def declared_queues(jobs=None) -> frozenset[str]:
    specs = (registry.jobs if jobs is None else jobs).specs()
    return frozenset({settings.CELERY_TASK_DEFAULT_QUEUE, *(spec.queue for spec in specs)})


def routes(jobs=None) -> dict[str, dict[str, str]]:
    """Exact task name → queue. No globs and no module-path keys, so nothing can silently miss."""
    specs = (registry.jobs if jobs is None else jobs).specs()
    return {spec.name: {"queue": spec.queue} for spec in specs}
