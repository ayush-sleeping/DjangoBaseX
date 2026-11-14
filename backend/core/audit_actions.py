"""
Core's audit-action catalog (DATA_LIFECYCLE.md § 4.5): the label, tone and channel for every verb
core, users and rbac write. Registered from CoreConfig.ready() beside the other catalogs; a plugin
registers its own the same way. An action NOT listed here still logs (a missing label must not lose
a row), but a source scan (tests/architecture/test_every_audit_action_literal_is_registered) fails
the build for it, so the catalog cannot rot.
"""

from core.registry import Registry

# (key, label, tone, channel)
ACTIONS = (
    ("auth.login", "Signed in", "info", "auth"),
    ("auth.logout", "Signed out", "neutral", "auth"),
    ("auth.password_changed", "Password changed", "security", "auth"),
    ("auth.password_confirmed", "Password confirmed for a sensitive action", "info", "auth"),
    ("auth.password_confirm_failed", "Password confirmation failed", "warning", "auth"),
    ("auth.password_reset_requested", "Password reset requested", "info", "auth"),
    ("auth.password_reset", "Password reset", "security", "auth"),
    ("auth.sessions_revoked", "Other sessions revoked", "security", "auth"),
    ("auth.token_reuse_detected", "Refresh-token reuse detected", "danger", "security"),
    ("auth.mfa_setup_started", "Two-factor setup started", "info", "auth"),
    ("auth.mfa_enabled", "Two-factor enabled", "success", "auth"),
    ("auth.mfa_disabled", "Two-factor disabled", "security", "auth"),
    ("auth.mfa_recovery_code_used", "Two-factor recovery code used", "warning", "auth"),
    ("authz.superuser_bypass", "Superuser bypass of a permission check", "security", "security"),
    ("rbac.role.created", "Role created", "success", "rbac"),
    ("rbac.role.updated", "Role updated", "info", "rbac"),
    ("rbac.role.deleted", "Role deleted", "warning", "rbac"),
    ("rbac.role.assigned", "Role assigned", "info", "rbac"),
    ("rbac.role.revoked", "Role revoked", "warning", "rbac"),
    ("rbac.role.grants_changed", "Role permissions changed", "info", "rbac"),
    ("core.bulk.completed", "Bulk action completed", "info", "data"),
    ("core.dataio.exported", "Data exported", "info", "data"),
    ("core.dataio.imported", "Data imported", "info", "data"),
    ("users.user.created", "User created", "success", "rbac"),
    ("users.user.updated", "User updated", "info", "rbac"),
    ("users.user.activated", "User activated", "info", "rbac"),
    ("users.user.deactivated", "User deactivated", "warning", "rbac"),
    ("users.user.bootstrapped", "First administrator created", "security", "rbac"),
    ("users.sessions.revoked", "A user's sessions revoked", "security", "security"),
    ("users.invitation.sent", "Invitation sent", "info", "rbac"),
    ("users.invitation.accepted", "Invitation accepted", "success", "rbac"),
    ("users.invitation.revoked", "Invitation revoked", "warning", "rbac"),
    ("core.setting.changed", "Setting changed", "info", "settings"),
    ("core.setting.reset", "Setting reset to its default", "info", "settings"),
    ("core.flag.changed", "Feature flag changed", "info", "settings"),
    ("core.lookup.created", "Lookup value added", "info", "settings"),
    ("core.lookup.changed", "Lookup value changed", "info", "settings"),
    ("core.webhook.created", "Webhook endpoint created", "success", "security"),
    ("core.webhook.repointed", "Webhook endpoint URL changed", "security", "security"),
    ("core.webhook.secret_rotated", "Webhook signing secret rotated", "security", "security"),
    ("core.webhook.deleted", "Webhook endpoint deleted", "warning", "security"),
    ("core.api_consumer.created", "API consumer created", "success", "security"),
    ("core.api_consumer.updated", "API consumer changed", "info", "security"),
    ("core.api_consumer.deactivated", "API consumer deactivated", "warning", "security"),
    ("core.api_consumer.activated", "API consumer reactivated", "security", "security"),
    ("core.api_token.issued", "API token issued", "security", "security"),
    ("core.api_token.rotated", "API token rotated", "security", "security"),
    ("core.api_token.scopes_changed", "API token scopes changed", "security", "security"),
    ("core.api_token.revoked", "API token revoked", "warning", "security"),
    ("core.notification_route.saved", "Notification route saved", "security", "security"),
    ("core.notification_route.deleted", "Notification route deleted", "warning", "security"),
    ("core.notification_matrix.changed", "Notification matrix changed", "info", "settings"),
    ("core.notification.test_sent", "Notification test sent", "info", "settings"),
    ("core.recycle_bin.restored", "Record restored from the recycle bin", "success", "data"),
    ("core.recycle_bin.force_deleted", "Record deleted for good from the bin", "danger", "data"),
    ("core.command.ran", "Management command ran", "neutral", "data"),
    ("core.retention.purged", "Retention removed rows", "warning", "data"),
    ("core.audit.exported", "Audit log exported", "security", "security"),
    ("guard.would_block", "A guard would have blocked this (log-only)", "warning", "security"),
    ("guard.blocked", "A guard blocked this", "danger", "security"),
)


def register_core_actions(registry: Registry) -> None:
    for key, label, tone, channel in ACTIONS:
        registry.audit_actions.register(key=key, label=label, tone=tone, channel=channel)
