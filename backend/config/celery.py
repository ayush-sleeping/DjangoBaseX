"""
The Celery app: the composition root for workers and beat (JOBS_AND_INTEGRATIONS.md § 3, ADR-0012).

    celery -A config worker -Q default,bulk -n default@%h
    celery -A config beat          (exactly one; DatabaseScheduler, synced from the registry)

Every CELERY_* setting is in config/settings.py. The tasks, queues and routes are generated from the
job registry by core.jobs.celery.install(), which runs when the app finalizes: by then Django is set
up and every app has registered its jobs.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")


@app.on_after_finalize.connect
def _install_jobs(sender, **kwargs):
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()
    from core.jobs.celery import install

    install(sender)
