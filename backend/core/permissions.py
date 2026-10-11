"""
The declarative gate (AUTH_BLUEPRINT § 7.5, § 9.1). core never imports rbac; they meet at has_perm.

A view states what it needs on the class, in one place:

    required_permissions = None          → denies everyone (the default: forgetting closes the door)
    required_permissions = []            → any signed-in user
    required_permissions = ["a.b.c"]     → every listed code (BaseAPIView)
    required_permissions = {"list": [...], "create": [...]}   → per action (BaseViewSet);
                                           an action missing from the dict denies
    public = True                        → anyone; the URL name must be in core.routes.PUBLIC_ROUTES
"""

from rest_framework.permissions import BasePermission


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
