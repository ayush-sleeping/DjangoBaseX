"""
Everything this plugin contributes to the platform, registered at boot from AppConfig.ready()
(CORE_ARCHITECTURE_PLAN § 2). Core never names this plugin: it only reads the registries.

Imports core.registry and nothing else. A plugin never imports another plugin, or project.
"""

from core.registry import NavItem, NavSection, PermissionGroupSpec, PermissionSpec, registry

VIEW = PermissionSpec(code="notes.notes.view", label="View notes")
CREATE = PermissionSpec(code="notes.notes.create", label="Create notes")
DELETE = PermissionSpec(code="notes.notes.delete", label="Delete notes")

GROUP = PermissionGroupSpec(
    code="notes",
    label="Notes",
    module="notes",
    permissions=(VIEW, CREATE, DELETE),
)

SECTION = NavSection(
    key="notes",
    label="Notes",
    module="notes",
    items=(NavItem(key="home", label="Notes", path="/notes", permission=VIEW.code),),
)


def register() -> None:
    registry.permissions.register(GROUP)
    registry.api_routes.register(prefix="notes", urlconf="djx_notes.urls")
    registry.navigation.register(SECTION)
