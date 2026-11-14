"""
The soft-disable switch (EXTENSIBILITY § 15, BUILD_ORDER 9.1).

Disabling a plugin never unloads it, never migrates and never touches its data: it hides its
navigation, search sources, help pages and bootstrap sections, makes its routes answer 403
`plugin_disabled`, and makes its jobs skip at run time. Every surface asks registry.plugin_state;
this module only supplies WHERE the disabled set lives: the typed runtime setting
`core.plugins.disabled` (a list of plugin labels), so there is no table and no restart. A label
that is not listed is enabled (installing a plugin makes it live). Platform apps are not plugins
and cannot be listed: owner_label() never maps them to a label.
"""

from .plugins import RESERVED_LABELS
from .registry import Registry, plugin_state
from .settings_registry import SettingDef, StrList
from .settings_service import get_setting, set_value

DISABLED_KEY = "core.plugins.disabled"


def disabled_labels() -> frozenset[str]:
    """The provider behind registry.plugin_state: one snapshot read per request."""
    return frozenset(get_setting("core.plugins.disabled"))


def register(reg: Registry) -> None:
    reg.settings.register(
        SettingDef(
            key=DISABLED_KEY,
            type=StrList(),
            default=(),
            label="Disabled plugins",
            description=(
                "Plugin labels switched off. Their navigation, search sources, help pages and "
                "bootstrap sections are hidden, their routes answer 403 plugin_disabled and their "
                "jobs skip. No data is changed; removing a label restores everything."
            ),
            group="Extensions",
            module="core",
            changed_by_event="A plugin misbehaves, or a feature is retired without uninstalling it",
            used_by=("Navigation", "API routes", "Background jobs", "Search", "Help", "Bootstrap"),
        )
    )
    plugin_state.use(disabled_labels)


def set_enabled(label: str, enabled: bool, *, actor=None, reason: str = "") -> None:
    """Switch one plugin on or off through the settings service (audited there)."""
    if label in RESERVED_LABELS:
        raise ValueError(f"{label!r} is a platform app: it cannot be disabled")
    current = set(disabled_labels())
    current.discard(label) if enabled else current.add(label)
    set_value("core.plugins.disabled", sorted(current), actor=actor, reason=reason)
