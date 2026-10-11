"""
The two system roles, as rows only (AUTH_BLUEPRINT § 8.1, § 13 #6). Grants are NOT made here: at
migration time the permission table is empty, so "administrator gets everything" would grant
nothing. rbac.apps' post_migrate handler recomputes administrator after seeding the catalog.
Frozen: uses the historical model, imports no application code.
"""

from django.db import migrations

SYSTEM_ROLES = [
    {
        "slug": "administrator",
        "name": "Administrator",
        "description": "Every permission in the catalog, recomputed after every migrate.",
        "is_elevated": True,
    },
    {
        "slug": "staff",
        "name": "Staff",
        "description": "Grants nothing. The safe default for a new account.",
        "is_elevated": False,
    },
]


def create_roles(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for spec in SYSTEM_ROLES:
        Role.objects.update_or_create(
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "is_system": True,
                "is_elevated": spec["is_elevated"],
            },
        )


def remove_roles(apps, schema_editor):
    # Reversible, but never at the cost of someone's access: roles still held stay (PROTECT).
    Role = apps.get_model("rbac", "Role")
    UserRole = apps.get_model("rbac", "UserRole")
    for spec in SYSTEM_ROLES:
        if not UserRole.objects.filter(role__slug=spec["slug"]).exists():
            Role.objects.filter(slug=spec["slug"], is_system=True).delete()


class Migration(migrations.Migration):
    dependencies = [("rbac", "0001_initial")]

    operations = [migrations.RunPython(create_roles, remove_roles)]
