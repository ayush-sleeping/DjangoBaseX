from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import checks  # noqa: F401 — registers the dbx.* system checks
        from .registry import registry
        from .routes import CORE_PUBLIC_ROUTES

        for url_name, reason in CORE_PUBLIC_ROUTES.items():
            registry.public_routes.register(url_name, reason)
