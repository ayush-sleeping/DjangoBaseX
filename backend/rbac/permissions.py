"""The rbac module's permission catalog (AUTH_BLUEPRINT § 7.1). Registered in RbacConfig.ready()."""

from core.registry import PermissionGroupSpec, PermissionSpec

GROUP = PermissionGroupSpec(
    code="rbac",
    label="Roles & Permissions",
    module="rbac",
    order=20,
    permissions=(
        PermissionSpec("rbac.roles.view", "View roles"),
        PermissionSpec("rbac.roles.manage", "Create, edit and assign roles"),
    ),
)
