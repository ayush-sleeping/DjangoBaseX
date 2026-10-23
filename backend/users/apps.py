from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"

    def ready(self):
        from core.registry import registry

        from . import signals
        from .permissions import GROUP

        signals.connect()
        registry.permissions.register(GROUP)
        from .reauth import ReauthPolicy

        registry.settings.register_group(
            ReauthPolicy, prefix="security.reauth", module="users", group="Re-authentication"
        )
        from .public_routes import PUBLIC_ROUTES

        for url_name, reason in PUBLIC_ROUTES.items():
            registry.public_routes.register(url_name, reason)
