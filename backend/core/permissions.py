"""Layer 1 entity permission (§ 7.5). core never imports rbac; they meet at has_perm."""

from rest_framework.permissions import BasePermission


class HasPermission(BasePermission):
    """Requires every code in `codes`. Build one with has_permission("module.feature.action")."""

    codes: tuple[str, ...] = ()

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return all(user.has_perm(code) for code in self.codes)


def has_permission(*codes: str) -> type[HasPermission]:
    if not codes:
        raise ValueError("has_permission() needs at least one permission code")
    return type(f"HasPermission[{','.join(codes)}]", (HasPermission,), {"codes": codes})
