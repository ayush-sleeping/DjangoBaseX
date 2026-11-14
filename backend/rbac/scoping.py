"""rbac's declarations for registry.scoping (DATA_LIFECYCLE.md § 12.1)."""

from core.registry import ScopeSpec

SPECS = (
    ScopeSpec("rbac.Role"),
    ScopeSpec(
        "rbac.UserRole",
        owner_field="user",
        not_scoped_because=(
            "Reached only through UserRoleViewSet, which resolves the user through "
            "User.objects.visible_to() first."
        ),
    ),
)
