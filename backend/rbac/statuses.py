"""The statuses the rbac app shows (FRONTEND_PLATFORM § 13). Registered from RbacConfig.ready()."""

from core.registry import StatusSpec, registry

STATUSES = (
    StatusSpec("rbac.role.system", "System", "neutral"),
    StatusSpec("rbac.role.elevated", "Elevated", "warn"),
    StatusSpec("rbac.role.mfa_required", "Two-factor required", "info"),
)


def register() -> None:
    for spec in STATUSES:
        registry.statuses.register(spec)
