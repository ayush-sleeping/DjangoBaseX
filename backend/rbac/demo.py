"""
Demo role and assignments (BUILD_ORDER 9.6), through `rbac.services`.

Runs after `users` (INSTALLED_APPS order). Natural keys: the role slug, and (user, role). A demo
user that does not exist is skipped, not invented.
"""

from django.contrib.auth import get_user_model

from core.seeding import DEMO_DOMAIN, SeedResult
from rbac import services
from rbac.models import Role, UserRole
from rbac.seeding import sync_catalog

SUPPORT_SLUG = "demo-support"
SUPPORT_GRANTS = ("users.users.view", "rbac.roles.view")
ASSIGNMENTS = (
    (f"admin@{DEMO_DOMAIN}", services.ADMINISTRATOR),
    (f"support@{DEMO_DOMAIN}", SUPPORT_SLUG),
    (f"viewer@{DEMO_DOMAIN}", services.STAFF),
)


def seed(stdout) -> SeedResult:
    result = SeedResult()
    sync_catalog()
    services.ensure_system_roles()
    services.recompute_administrator()
    if Role.objects.filter(slug=SUPPORT_SLUG).exists():
        result.skipped += 1
    else:
        services.create_role(
            actor=None,
            name="Demo support",
            slug=SUPPORT_SLUG,
            description="Read-only access to users and roles, for demos.",
            permission_codes=SUPPORT_GRANTS,
        )
        result.created += 1
    user_model = get_user_model()
    for email, slug in ASSIGNMENTS:
        user = user_model.objects.filter(email=email).first()
        if user is None:
            stdout.write(f"skipped {email}: not there (run the users seeder first)")
            continue
        role = Role.objects.get(slug=slug)
        if UserRole.objects.filter(user=user, role=role).exists():
            result.skipped += 1
            continue
        services.assign_role(actor=None, user=user, role=role)
        result.created += 1
    return result
