import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import checks  # noqa: F401 — registers the dbx.* system checks
        from .dataplane import register_core_checks
        from .observability.health import HEALTH_GROUP
        from .permissions import AUDIT_GROUP, SETTINGS_GROUP
        from .registry import registry
        from .routes import CORE_PUBLIC_ROUTES

        for url_name, reason in CORE_PUBLIC_ROUTES.items():
            registry.public_routes.register(url_name, reason)
        registry.permissions.register(SETTINGS_GROUP)
        registry.permissions.register(AUDIT_GROUP)
        registry.permissions.register(HEALTH_GROUP)
        register_core_checks()
        from .audit_actions import register_core_actions
        from .formatting import register_locale_settings

        register_locale_settings(registry)
        register_core_actions(registry)
        _register_jobs_monitoring(registry)
        from .outbox.jobs import register as register_outbox

        register_outbox(registry)
        from .crypto import self_test

        # A process that cannot encrypt must refuse to start, not store plaintext (§ 25). An empty
        # keyring in development is not a failure; production-like boots refuse it via cfg.E013.
        self_test()
        post_migrate.connect(_report_settings, sender=self, dispatch_uid="core.settings_report")
        post_migrate.connect(_seed_lookups, sender=self, dispatch_uid="core.seed_lookups")
        post_migrate.connect(_sync_schedules, sender=self, dispatch_uid="core.sync_schedules")


def _register_jobs_monitoring(registry) -> None:
    """The run monitor's settings, its non-critical health check and the doctors (BUILD_ORDER 7.2;
    JOBS_AND_INTEGRATIONS § 8, OBSERVABILITY § 12)."""
    from .dataplane import doctor_findings
    from .jobs import doctors as job_doctors
    from .jobs.health import GREEN, QueuePolicy, report
    from .registry import Doctor, HealthCheck

    registry.settings.register_group(
        QueuePolicy, prefix="operations.queue", module="operations", group="Background jobs"
    )
    # Not critical: a stalled queue must never take the web tier out of the load balancer.
    registry.health.register(
        HealthCheck(
            key="jobs",
            label="Background jobs",
            check=lambda: report().status == GREEN,
            critical=False,
        )
    )
    for doctor in (
        Doctor(
            key="dataplane",
            fn=doctor_findings,
            owner="core",
            description="Required rows exist and make sense (OBSERVABILITY.md § 7).",
        ),
        Doctor(
            key="queue",
            fn=job_doctors.queue_doctor,
            owner="core",
            description="Celery settings, stalled queues, queues with no consumer, dead and "
            "unregistered tasks (JOBS_AND_INTEGRATIONS.md § 8).",
        ),
        Doctor(
            key="schedule",
            fn=job_doctors.schedule_doctor,
            owner="core",
            description="Beat in sync with the registry; scheduled jobs failing, overdue or never "
            "run; unowned beat rows (JOBS_AND_INTEGRATIONS.md § 6, § 8).",
        ),
    ):
        registry.doctors.register(doctor)


def _report_settings(sender, **kwargs):
    """
    sync_settings after every migrate: it reports, it never writes (CONFIGURATION.md § 9.2), so a
    re-run cannot reset an admin's value. Settings metadata lives in code; there is nothing to sync.
    """
    from .settings_service import report

    log = logging.getLogger("core.settings")
    for finding in report():
        log.warning(
            "core.setting.stored_problem",
            extra={"setting_key": finding.key, "scope": finding.scope, "problem": finding.problem},
        )


def _seed_lookups(sender, **kwargs):
    """sync_lookups after every migrate: inserts MISSING seed keys only (CONFIGURATION.md § 14) —
    it never relabels, reactivates or deletes, so the admin's edits survive every reseed."""
    from .lookups import sync_lookups

    for created in sync_lookups():
        logging.getLogger("core.lookups").info("core.lookup.seeded", extra={"value": created})


def _sync_schedules(sender, **kwargs):
    """sync_schedules after every migrate (JOBS_AND_INTEGRATIONS.md § 6): beat's rows follow the
    registry, so a schedule is never created by hand or frozen into a data migration."""
    from django.apps import apps

    # A migrate that stops short of django_celery_beat's tables (`migrate core 0001`) has nothing
    # to sync into yet.
    if not apps.is_installed("django_celery_beat"):
        return
    from django.db import DEFAULT_DB_ALIAS, connections

    tables = set(connections[kwargs.get("using", DEFAULT_DB_ALIAS)].introspection.table_names())
    if not {"django_celery_beat_periodictask", "core_job_schedule"} <= tables:
        return
    from .jobs.schedules import sync_schedules

    report = sync_schedules()
    log = logging.getLogger("core.jobs")
    for action in ("created", "updated", "deleted"):
        for name in getattr(report, action):
            log.info(f"core.job.schedule_{action}", extra={"job": name})
