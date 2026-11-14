"""users' declarations for registry.scoping (DATA_LIFECYCLE.md § 12.1)."""

from core.registry import ScopeSpec

_AUTH_RECORD = (
    "Authentication record reached only through the auth/MFA/session services for the user "
    "concerned; no viewset lists it across users."
)

SPECS = (
    ScopeSpec("users.User"),
    ScopeSpec("users.UserSession", owner_field="user", not_scoped_because=_AUTH_RECORD),
    ScopeSpec("users.LoginAttempt", owner_field="user", not_scoped_because=_AUTH_RECORD),
    ScopeSpec("users.MfaDevice", owner_field="user", not_scoped_because=_AUTH_RECORD),
    ScopeSpec("users.MfaRecoveryCode", owner_field="user", not_scoped_because=_AUTH_RECORD),
    ScopeSpec("users.PasswordResetToken", owner_field="user", not_scoped_because=_AUTH_RECORD),
)
