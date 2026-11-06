"""
The statuses the users app shows (FRONTEND_PLATFORM § 13): the tone of each is decided here, once,
and the frontend renders it. Registered from UsersConfig.ready().
"""

from core.registry import StatusSpec, registry

STATUSES = (
    StatusSpec("users.user.active", "Active", "ok"),
    StatusSpec("users.user.deactivated", "Deactivated", "err"),
    StatusSpec("users.user.superuser", "Superuser", "warn"),
    StatusSpec("users.user.mfa_on", "Two-factor on", "info"),
    StatusSpec("users.invitation.pending", "Pending", "info", transitional=True),
    StatusSpec("users.invitation.accepted", "Accepted", "ok"),
    StatusSpec("users.invitation.revoked", "Revoked", "neutral"),
    StatusSpec("users.invitation.expired", "Expired", "warn"),
)


def register() -> None:
    for spec in STATUSES:
        registry.statuses.register(spec)
