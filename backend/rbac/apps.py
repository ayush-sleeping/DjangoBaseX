from django.apps import AppConfig
from django.db.models.signals import post_migrate


class RbacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rbac"

    def ready(self):
        from core.registry import registry

        from .permissions import GROUP

        registry.permissions.register(GROUP)
        from users.signals import invitation_accepted

        invitation_accepted.connect(_assign_invited_role, dispatch_uid="rbac.assign_invited_role")
        # After every migrate the catalog is in the database, so a fresh one is usable at once.
        post_migrate.connect(_seed_after_migrate, sender=self, dispatch_uid="rbac.seed_catalog")


def _seed_after_migrate(sender, **kwargs):
    # Order matters (AUTH_BLUEPRINT § 13): the catalog first, then the roles, then the grants.
    # A role migration cannot grant administrator anything: at that point no permission exists.
    from .seeding import sync_catalog
    from .services import ensure_system_roles, recompute_administrator

    sync_catalog()
    ensure_system_roles()
    recompute_administrator()


def _assign_invited_role(sender, user, role_id, invited_by=None, **kwargs):
    # The elevated-role check happened when the invitation was sent (users.services.invitations);
    # here the system completes what an authorised person already decided.
    from .models import Role
    from .services import assign_role

    assign_role(actor=None, user=user, role=Role.objects.get(pk=role_id))
