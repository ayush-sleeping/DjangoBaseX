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


# The audit verbs services.py emits (DATA_LIFECYCLE § 4). A plugin declares its own, under its
# label; core never lists them.
AUDIT_ACTIONS = (
    ("notes.note.created", "Note created", "success"),
    ("notes.note.deleted", "Note deleted", "warning"),
)


def register() -> None:
    registry.permissions.register(GROUP)
    registry.api_routes.register(prefix="notes", urlconf="djx_notes.urls")
    registry.navigation.register(SECTION)
    for key, label, tone in AUDIT_ACTIONS:
        registry.audit_actions.register(key=key, label=label, tone=tone, channel="notes")
