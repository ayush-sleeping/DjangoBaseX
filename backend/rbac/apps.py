from django.apps import AppConfig
from django.db.models.signals import post_migrate


class RbacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rbac"

    def ready(self):
        from core.registry import registry

        from .permissions import GROUP

        registry.permissions.register(GROUP)
        # After every migrate the catalog is in the database, so a fresh one is usable at once.
        post_migrate.connect(_seed_after_migrate, sender=self, dispatch_uid="rbac.seed_catalog")


def _seed_after_migrate(sender, **kwargs):
    from .seeding import sync_catalog

    sync_catalog()
