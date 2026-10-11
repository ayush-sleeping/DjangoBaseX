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
