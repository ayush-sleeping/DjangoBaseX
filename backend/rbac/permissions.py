"""The rbac module's permission catalog (AUTH_BLUEPRINT § 7.1, § 10.3). Registered in ready()."""

from core.registry import PermissionGroupSpec, PermissionSpec

GROUP = PermissionGroupSpec(
    code="rbac",
    label="Roles & Permissions",
    module="rbac",
    order=20,
    permissions=(
        PermissionSpec("rbac.permissions.view", "View the permission catalog"),
        PermissionSpec("rbac.roles.view", "View roles"),
        PermissionSpec("rbac.roles.create", "Create roles"),
        PermissionSpec("rbac.roles.update", "Edit roles and their permissions"),
        PermissionSpec("rbac.roles.delete", "Delete roles"),
        PermissionSpec("rbac.roles.assign", "Assign and revoke roles"),
    ),
)
