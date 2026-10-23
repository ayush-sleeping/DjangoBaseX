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
        from .permissions import SETTINGS_GROUP
        from .registry import registry
        from .routes import CORE_PUBLIC_ROUTES

        for url_name, reason in CORE_PUBLIC_ROUTES.items():
            registry.public_routes.register(url_name, reason)
        registry.permissions.register(SETTINGS_GROUP)
        registry.permissions.register(HEALTH_GROUP)
        register_core_checks()
        from .formatting import register_locale_settings

        register_locale_settings(registry)
        from .crypto import self_test

        # A process that cannot encrypt must refuse to start, not store plaintext (§ 25). An empty
        # keyring in development is not a failure; production-like boots refuse it via cfg.E013.
        self_test()
        post_migrate.connect(_report_settings, sender=self, dispatch_uid="core.settings_report")
        post_migrate.connect(_seed_lookups, sender=self, dispatch_uid="core.seed_lookups")


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
