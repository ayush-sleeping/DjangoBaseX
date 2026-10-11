"""
RBAC tables (AUTH_BLUEPRINT § 3.7–3.11). Permissions are declared in code (core.registry) and
projected here by rbac.seeding; the table is never the source. Roles hold grants; users hold roles.
Every write goes through rbac.services, never the admin (Ch. 20).
"""

import uuid

from django.conf import settings
from django.db import models

from core.querysets import VisibleToQuerySet


class PermissionGroup(models.Model):
    """UI grouping only. Nothing may branch on a group (§ 3.7)."""

    code = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=128)
    module = models.CharField(max_length=64, db_index=True)
    order = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "rbac_permission_group"
        ordering = ["order", "code"]

    def __str__(self):
        return self.code


class Permission(models.Model):
    """One capability, `<module>.<feature>.<action>`. A projection of the code catalog (§ 3.8)."""

    code = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=128)
    group = models.ForeignKey(PermissionGroup, on_delete=models.PROTECT, related_name="permissions")
    module = models.CharField(max_length=64, db_index=True)
    # Left the catalog but kept: deleting would cascade away real grants (seeding never deletes).
    is_deprecated = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rbac_permission"
        ordering = ["code"]

    def __str__(self):
        return self.code


class RoleQuerySet(VisibleToQuerySet):
    def visible_to(self, user):
        if user is None or not user.is_authenticated or not user.has_perm("rbac.roles.view"):
            return self.none()
        return self.all()


class Role(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(max_length=64, unique=True)  # what code refers to
    description = models.CharField(max_length=255, blank=True, default="")
    is_system = models.BooleanField(default=False, db_index=True)  # cannot be renamed or deleted
    is_elevated = models.BooleanField(default=False)  # only a superuser may grant it (§ 8.2)
    mfa_required = models.BooleanField(default=False)  # holding it forces user.mfa_enforced
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    permissions = models.ManyToManyField(
        Permission, through="RolePermission", related_name="roles", blank=True
    )

    objects = RoleQuerySet.as_manager()

    class Meta:
        db_table = "rbac_role"
        ordering = ["name"]

    def __str__(self):
        return self.slug


class RolePermission(models.Model):
    """The grant, with who widened the role and when — the first question after an incident."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(
        Permission, on_delete=models.CASCADE, related_name="role_permissions"
    )
    granted_at = models.DateTimeField()
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "rbac_role_permission"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="rbac_role_permission_once")
        ]

    def __str__(self):
        return f"{self.role_id}:{self.permission_id}"


class UserRole(models.Model):
    """The assignment. A user's permissions are the union over their roles."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles"
    )
    # PROTECT: deleting a role must never silently remove someone's access (§ 3.11).
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")
    assigned_at = models.DateTimeField()
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "rbac_user_role"
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="rbac_user_role_once")]

    def __str__(self):
        return f"{self.user_id}:{self.role_id}"
