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

from core.api.error_codes import ApiError
from core.registry import PermissionGroupSpec, PermissionSpec


class DefaultDeny(BasePermission):
    """DRF's DEFAULT_PERMISSION_CLASSES (dbx.E004): a view that skips the bases serves nobody."""

    def has_permission(self, request, view):
        return False


class CredentialKindAllowed(BasePermission):
    """
    API_PLATFORM.md § 7: a view accepts the credential kinds it declares (default: session only).
    A machine principal reaches a view only if it opts in with credential_kinds including "token",
    and never a human_only view, whatever the scopes.
    """

    def has_permission(self, request, view):
        user = request.user
        if getattr(view, "public", False) or not user or not user.is_authenticated:
            return True  # anonymous: IsAuthenticated answers 401
        kind = "token" if getattr(user, "is_machine", False) else "session"
        accepted = getattr(view, "credential_kinds", frozenset({"session"}))
        if kind not in accepted or (kind == "token" and getattr(view, "human_only", False)):
            raise ApiError("credential_not_accepted")
        return True


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


API_CONSUMERS_GROUP = PermissionGroupSpec(
    code="api_consumers",
    label="API consumers",
    module="core",
    order=98,
    permissions=(
        PermissionSpec("core.api_consumers.view", "View API consumers and their tokens"),
        PermissionSpec(
            "core.api_consumers.manage", "Create, describe and deactivate API consumers"
        ),
        PermissionSpec("core.api_tokens.issue", "Issue, rotate and re-scope API tokens"),
        PermissionSpec("core.api_tokens.revoke", "Revoke API tokens"),
    ),
)


FILES_GROUP = PermissionGroupSpec(
    code="files",
    label="Files",
    module="core",
    order=99,
    permissions=(
        PermissionSpec("core.files.upload", "Upload files (content-checked, stored privately)"),
        PermissionSpec("core.files.view", "Download files of the general purpose"),
    ),
)


WEBHOOKS_GROUP = PermissionGroupSpec(
    code="webhooks",
    label="Webhooks",
    module="core",  # platform-owned endpoints until API consumers exist (BUILD_ORDER 9.2)
    order=96,
    permissions=(
        PermissionSpec("core.webhooks.view", "View webhook endpoints and their delivery log"),
        PermissionSpec(
            "core.webhooks.manage",
            "Create, change, rotate and delete webhook endpoints; redeliver; send a test",
        ),
    ),
)


NOTIFICATIONS_GROUP = PermissionGroupSpec(
    code="notifications",
    label="Notifications",
    module="core",
    order=97,
    permissions=(
        PermissionSpec(
            "core.notifications.view", "View notification routes, the matrix and the delivery log"
        ),
        PermissionSpec(
            "core.notifications.manage",
            "Edit notification routes and the event x channel matrix; send a test",
        ),
    ),
)
