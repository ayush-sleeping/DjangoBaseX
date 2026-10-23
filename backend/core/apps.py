import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import checks  # noqa: F401 — registers the dbx.* system checks
        from .permissions import SETTINGS_GROUP
        from .registry import registry
        from .routes import CORE_PUBLIC_ROUTES

        for url_name, reason in CORE_PUBLIC_ROUTES.items():
            registry.public_routes.register(url_name, reason)
        registry.permissions.register(SETTINGS_GROUP)
        post_migrate.connect(_report_settings, sender=self, dispatch_uid="core.settings_report")


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
