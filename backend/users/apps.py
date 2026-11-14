from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"

    def ready(self):
        from core.registry import registry

        from . import signals
        from .permissions import GROUP

        signals.connect()
        registry.permissions.register(GROUP)
        from .reauth import ReauthPolicy

        registry.settings.register_group(
            ReauthPolicy, prefix="security.reauth", module="users", group="Re-authentication"
        )
        from core.registry import EncryptedField

        registry.encrypted_fields.register(
            EncryptedField(
                model="users.MfaDevice", field="totp_secret_ciphertext", purpose="mfa_totp"
            )
        )
        from core.registry import StateField

        registry.state_fields.register(
            StateField(key="users.user.is_active", model="users.User", field="is_active")
        )
        from core.registry import StateMachine

        registry.state_machines.register(
            StateMachine(
                key="users.user.is_active",
                model="users.User",
                field="is_active",
                initial=True,
                transitions={True: {False}, False: {True}},
            )
        )
        from .bulk import ACTIONS as BULK_ACTIONS

        for bulk_action in BULK_ACTIONS:
            registry.bulk_actions.register(bulk_action)
        from .scoping import SPECS as SCOPING

        for scope_spec in SCOPING:
            registry.scoping.register(scope_spec)
        from .notifications import PURPOSES as NOTIFICATION_PURPOSES

        for notification_purpose in NOTIFICATION_PURPOSES:
            registry.notification_purposes.register(notification_purpose)
        from .events import EVENTS

        for event in EVENTS:
            registry.events.register(event)
        from .public_routes import PUBLIC_ROUTES

        for url_name, reason in PUBLIC_ROUTES.items():
            registry.public_routes.register(url_name, reason)
        from .jobs import AUTH_CLEANUP

        registry.jobs.register(AUTH_CLEANUP)
        from core.retention import register as register_retention

        from .retention import POLICIES as RETENTION_POLICIES

        for retention_policy in RETENTION_POLICIES:
            register_retention(registry, retention_policy)
        # Navigation is also the route gate (FRONTEND_PLATFORM § 10): every page needs an entry.
        from .bootstrap import register as register_bootstrap

        register_bootstrap()
        from .navigation import register as register_navigation

        register_navigation()
        # Status tones (FRONTEND_PLATFORM § 13) and the OpenAPI description of cookie auth (§ 24).
        from . import schema  # noqa: F401 — registers the auth extension with drf-spectacular
        from .statuses import register as register_statuses

        register_statuses()
