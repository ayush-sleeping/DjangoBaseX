"""
The declarative gate (AUTH_BLUEPRINT § 7.5, § 9.1). core never imports rbac; they meet at has_perm.

A view states what it needs on the class, in one place:

    required_permissions = None          → denies everyone (the default: forgetting closes the door)
    required_permissions = []            → any signed-in user
    required_permissions = ["a.b.c"]     → every listed code (BaseAPIView)
    required_permissions = {"list": [...], "create": [...]}   → per action (BaseViewSet);
                                           an action missing from the dict denies
    public = True                        → anyone; the URL name must be in registry.public_routes
"""

from rest_framework.permissions import BasePermission

from core.registry import PermissionGroupSpec, PermissionSpec


class DefaultDeny(BasePermission):
    """DRF's DEFAULT_PERMISSION_CLASSES (dbx.E004): a view that skips the bases serves nobody."""

    def has_permission(self, request, view):
        return False


class HasPermission(BasePermission):
    def has_permission(self, request, view):
        if getattr(view, "public", False):
            return True
        user = request.user
        if not user or not user.is_authenticated:
            return False
        codes = required_codes(view)
        if codes is None:
            return False
        return all(user.has_perm(code) for code in codes)


def required_codes(view) -> list[str] | None:
    """The codes this request needs, or None when the view has not declared any (deny)."""
    declared = getattr(view, "required_permissions", None)
    if isinstance(declared, dict):
        return declared.get(getattr(view, "action", None))
    return declared


# --- core's own permission catalog (registered in CoreConfig.ready, like users' and rbac's) -------

SETTINGS_GROUP = PermissionGroupSpec(
    code="settings",
    label="Settings",
    module="settings",  # RBAC_DESIGN.md: settings.settings.manage is core's, under "settings."
    order=30,
    permissions=(
        PermissionSpec("settings.settings.view", "View settings and their effective values"),
        PermissionSpec("settings.settings.manage", "Change and reset settings"),
        PermissionSpec("settings.flags.view", "View feature flags, targeting and expiry"),
        PermissionSpec("settings.flags.manage", "Toggle feature flags and change targeting"),
        PermissionSpec("settings.lookups.manage", "Add and edit lookup values and labels"),
        PermissionSpec(
            "settings.crypto.view", "View encryption key fingerprints and rotation state"
        ),
    ),
)


AUDIT_GROUP = PermissionGroupSpec(
    code="audit",
    label="Audit log",
    module="core",  # core.audit.view reads the full log; there is NO write permission (§ 4.6)
    order=95,
    permissions=(
        PermissionSpec("core.audit.view", "Read the audit log"),
        PermissionSpec("core.audit.export", "Export the audit log (the export is itself audited)"),
    ),
)
