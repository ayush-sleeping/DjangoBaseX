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
    PermissionGroupSpec,
    PermissionSpec,
    SearchSource,
    ServiceContractError,
    ServiceUnavailable,
    plugin_state,
    registry,
)

SDK_VERSION = (1, 0)

# One entry per minor: what was added and why.
SDK_CHANGELOG = {
    (1, 0): (
        "First facade: the registry and its contribution specs, service-contract calls, "
        "plugin_enabled, and the lazily-loaded views, queryset base, audit log, settings and "
        "flag reads that plugins used to import from core internals."
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
}


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'core.sdk' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)


__all__ = [
    "BaseAPIView",
    "BaseViewSet",
    "BootstrapContributor",
    "Cron",
    "HelpPage",
    "Interval",
    "JobSpec",
    "NavItem",
    "NavSection",
    "NoProvider",
    "PermissionGroupSpec",
    "PermissionSpec",
    "SDKVersionError",
    "SDK_CHANGELOG",
    "SDK_VERSION",
    "SearchSource",
    "ServiceContractError",
    "ServiceUnavailable",
    "VisibleToQuerySet",
    "call_service",
    "error_response",
    "flag_enabled",
    "get_setting",
    "has_service",
    "invalid_response",
    "is_compatible",
    "log_activity",
    "plugin_enabled",
    "provide",
    "registry",
    "require_version",
]
