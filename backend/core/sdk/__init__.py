"""
The versioned SDK facade: the ONLY module a plugin imports from core (EXTENSIBILITY § 16,
BUILD_ORDER 9.1).

It re-exports the stable contracts and adds almost nothing of its own, so an internal refactor in
core moves an import HERE, once, instead of breaking every plugin. tests/architecture/
test_plugins_import_only_sdk.py fails a plugin that imports any other `core.*`, `users` or `rbac`.

SDK_VERSION is (major, minor). Adding an export is a minor bump and a SDK_CHANGELOG line;
removing, renaming or changing a signature is a major bump, preceded by one minor that emits
DeprecationWarning. A plugin calls require_version("1.0") at import and fails fast at boot when
the core it runs on is older (or a different major), not at its first call.

What needs Django to be fully loaded (views, querysets, the audit log) is exported lazily: a
plugin's models.py may import this module while apps are still loading.
"""

import importlib

from core.registry import (
    BootstrapContributor,
    Cron,
    HelpPage,
    Interval,
    JobSpec,
    NavItem,
    NavSection,
    NoProvider,
    NumberingSeries,
    PermissionGroupSpec,
    PermissionSpec,
    Recyclable,
    ScopeSpec,
    SearchSource,
    ServiceContractError,
    ServiceUnavailable,
    StateField,
    StateMachine,
    plugin_state,
    registry,
)

SDK_VERSION = (1, 3)

# One entry per minor: what was added and why.
SDK_CHANGELOG = {
    (1, 0): (
        "First facade: the registry and its contribution specs, service-contract calls, "
        "plugin_enabled, and the lazily-loaded views, queryset base, audit log, settings and "
        "flag reads that plugins used to import from core internals."
    ),
    (1, 1): (
        "Data lifecycle (BUILD_ORDER 9.3): SoftDeleteModel and its queryset/manager helpers, "
        "ProvenanceModel and stamp_provenance, Recyclable and register_recyclable, StateField and "
        "change_state, ScopeSpec and register_scoping."
    ),
    (1, 2): (
        "Domain primitives (BUILD_ORDER 9.4), needed by the first second product (10.1): "
        "NumberingSeries with peek_number/reserve_number, StateMachine with transition, "
        "allowed_transitions and its typed errors, and Money with money_fields/money_property."
    ),
    (1, 3): (
        "transition_options (each legal move with needs_reason, TECH_DEBT DB-137) and "
        "money_pair_check with optional money_fields (DB-139), from the second product's findings."
    ),
}


class SDKVersionError(Exception):
    """The plugin was built against an SDK this core does not provide."""


def is_compatible(target: str | tuple[int, int]) -> bool:
    """Same major, and this SDK's minor is at least the target's."""
    major, minor = _parse(target)
    return major == SDK_VERSION[0] and SDK_VERSION[1] >= minor


def require_version(target: str | tuple[int, int]) -> None:
    if not is_compatible(target):
        raise SDKVersionError(
            f"built against SDK {target}, but this core provides {SDK_VERSION[0]}.{SDK_VERSION[1]}"
        )


def _parse(target) -> tuple[int, int]:
    if isinstance(target, tuple) and len(target) == 2:
        return target
    try:
        major, minor = str(target).split(".")[:2]
        return int(major), int(minor)
    except ValueError:
        raise SDKVersionError(f"{target!r} is not a version like '1.0'") from None


def plugin_enabled(label: str) -> bool:
    """False when plugin `label` is soft-disabled (§ 15): the answer every registry uses."""
    return plugin_state.is_enabled(label)


def provide(name: str, impl) -> None:
    """Provide the service contract `name` (exactly one provider; § 18). Call from wiring."""
    registry.services.provide(name, impl)


def has_service(name: str) -> bool:
    return registry.services.has_service(name)


def call_service(name: str, **kwargs):
    """Raises NoProvider or ServiceUnavailable (both ServiceContractError) when it cannot answer."""
    return registry.services.call_service(name, **kwargs)


def register_recyclable(spec: Recyclable, *, days: int = 90) -> None:
    """Make a soft-deletable model listable and restorable in the recycle bin, and purge it after
    `days` (floor 7) through a retention policy. Call from wiring, after models load."""
    from core.lifecycle.recyclebin import register_recyclable as _register

    _register(registry, spec, days=days)


def register_scoping(spec: ScopeSpec) -> None:
    """Declare how a model of yours is scoped (or why it is not): required for any model with an
    owner or tenant field (tests/architecture/test_scoping.py)."""
    registry.scoping.register(spec)


# Needs Django loaded: resolved on first use (PEP 562).
_LAZY = {
    "BaseViewSet": "core.api.viewsets",
    "BaseAPIView": "core.api.views",
    "error_response": "core.api.errors",
    "invalid_response": "core.api.errors",
    "VisibleToQuerySet": "core.querysets",
    "log_activity": "core.audit",
    "get_setting": "core.settings_service",
    "flag_enabled": "core.flags",
    "SoftDeleteModel": "core.lifecycle.models",
    "SoftDeleteQuerySet": "core.lifecycle.models",
    "ProvenanceModel": "core.lifecycle.models",
    "RestoreConflict": "core.lifecycle.models",
    "SOURCE_REF_PATTERN": "core.lifecycle.models",
    "live_unique": "core.lifecycle.models",
    "soft_delete_managers": "core.lifecycle.models",
    "stamp_provenance": "core.lifecycle.provenance:stamp",
    "change_state": "core.lifecycle.transitions",
    "peek_number": "core.numbering:peek",
    "reserve_number": "core.numbering:reserve",
    "transition": "core.statemachine",
    "allowed_transitions": "core.statemachine:allowed_targets",
    "transition_options": "core.statemachine",
    "StateMachineError": "core.statemachine",
    "IllegalTransition": "core.statemachine",
    "ReasonRequired": "core.statemachine",
    "Money": "core.money",
    "MoneyError": "core.money",
    "to_money": "core.money",
    "money_fields": "core.money",
    "money_property": "core.money",
    "money_pair_check": "core.money",
}


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'core.sdk' has no attribute {name!r}")
    module, _, attr = module.partition(":")
    return getattr(importlib.import_module(module), attr or name)


__all__ = [
    "BaseAPIView",
    "BaseViewSet",
    "BootstrapContributor",
    "Cron",
    "HelpPage",
    "IllegalTransition",
    "Interval",
    "JobSpec",
    "Money",
    "MoneyError",
    "NavItem",
    "NavSection",
    "NoProvider",
    "NumberingSeries",
    "PermissionGroupSpec",
    "PermissionSpec",
    "ProvenanceModel",
    "ReasonRequired",
    "Recyclable",
    "RestoreConflict",
    "SDKVersionError",
    "SDK_CHANGELOG",
    "SDK_VERSION",
    "SOURCE_REF_PATTERN",
    "ScopeSpec",
    "SearchSource",
    "ServiceContractError",
    "ServiceUnavailable",
    "SoftDeleteModel",
    "SoftDeleteQuerySet",
    "StateField",
    "StateMachine",
    "StateMachineError",
    "VisibleToQuerySet",
    "allowed_transitions",
    "call_service",
    "change_state",
    "error_response",
    "flag_enabled",
    "get_setting",
    "has_service",
    "invalid_response",
    "is_compatible",
    "live_unique",
    "log_activity",
    "money_fields",
    "money_pair_check",
    "money_property",
    "peek_number",
    "plugin_enabled",
    "provide",
    "register_recyclable",
    "register_scoping",
    "registry",
    "require_version",
    "reserve_number",
    "soft_delete_managers",
    "stamp_provenance",
    "to_money",
    "transition",
    "transition_options",
]
