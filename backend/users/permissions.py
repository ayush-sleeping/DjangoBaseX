"""The users module's permission catalog (AUTH_BLUEPRINT § 7.1). Registered in UsersConfig.ready."""

from core.registry import PermissionGroupSpec, PermissionSpec

GROUP = PermissionGroupSpec(
    code="users",
    label="Users & Access",
    module="users",
    order=10,
    permissions=(
        PermissionSpec("users.users.view", "View users"),
        PermissionSpec("users.users.create", "Create users"),
        PermissionSpec("users.users.update", "Update users"),
        PermissionSpec("users.users.deactivate", "Activate / deactivate users"),
        PermissionSpec("users.users.export", "Export users"),
        PermissionSpec("users.invitations.send", "Invite users"),
        PermissionSpec("users.sessions.revoke", "Revoke another user's sessions"),
    ),
)
