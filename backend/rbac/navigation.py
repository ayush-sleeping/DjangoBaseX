"""
The rbac app's pages in the navigation, which is also the route gate (FRONTEND_PLATFORM § 10).
/settings/roles/<publicId> is gated by the "/settings/roles" prefix. Registered from
RbacConfig.ready().
"""

from core.registry import NavItem, NavSection, registry

SETTINGS = NavSection(
    key="settings",
    label="Settings",
    module="rbac",
    order=800,
    items=(NavItem("roles", "Roles", "/settings/roles", permission="rbac.roles.view"),),
)


def register() -> None:
    registry.navigation.register(SETTINGS)
