"""
The first-run setup (OPERATIONS.md § 3; BUILD_ORDER 9.5): the one service behind both
`manage.py bootstrap_admin` and the browser wizard, so whichever finishes first seals the other.

Setup is NEEDED exactly while no active superuser exists. That is the whole seal: there is no
"completed" flag to drift from the data, and deleting the last administrator reopens setup (an
install with no way in needs one). While needed, completing requires a one-time token, stored only
as a SHA-256 hash in the private setting `rbac.setup.token_hash` and issued by `manage.py
setup_token` to whoever has shell access: an unauthenticated caller who can merely reach a fresh
install cannot claim it. The token is cleared in the same transaction that creates the account.

Lives in rbac (it assigns a role) and reaches the user model through get_user_model().
"""

import hashlib
import hmac
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.db import transaction

from core.audit import log_activity
from core.settings_service import get_setting, reset, set_value

from . import services
from .models import Permission, Role
from .seeding import sync_catalog

TOKEN_KEY = "rbac.setup.token_hash"  # the scan wants literals at call sites; this one is for tests


class SetupError(Exception):
    """Base class; every subclass maps to one stable API error code."""

    code = "setup_error"


class SetupSealed(SetupError):
    code = "sealed"


class InvalidSetupToken(SetupError):
    code = "invalid_token"


def register(reg) -> None:
    """The token's hash lives in a private setting: no table, audited, cleared on completion, and
    the public ledger gains the two setup routes with the reason they are open."""
    from core.settings_registry import SettingDef, String

    reg.settings.register(
        SettingDef(
            key=TOKEN_KEY,
            type=String(),
            default="",
            label="First-run setup token (hash)",
            description=(
                "SHA-256 of the one-time token the first-run wizard asks for. Empty means no "
                "token has been issued and the wizard cannot complete. Cleared on completion."
            ),
            group="Setup",
            module="rbac",
            changed_by_event="An operator runs manage.py setup_token on a fresh install",
            used_by=("First-run setup",),
        )
    )
    reg.public_routes.register(
        "rbac:setup-status",
        "Tells the sign-in page whether first-run setup is pending: one boolean, nothing else.",
    )
    reg.public_routes.register(
        "rbac:setup-complete",
        "Authenticated by the one-time setup token; answers 404 once an administrator exists.",
    )


def needed() -> bool:
    """True while the install has no active superuser."""
    return not get_user_model().objects.filter(is_superuser=True, is_active=True).exists()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token() -> str:
    """Create (replacing any earlier one) the one-time setup token. Returned once, stored hashed."""
    if not needed():
        raise SetupSealed("setup is already complete")
    token = secrets.token_urlsafe(32)
    set_value("rbac.setup.token_hash", _hash(token), reason="setup token issued")
    return token


def verify_token(token: str) -> bool:
    stored = get_setting("rbac.setup.token_hash")
    return bool(stored) and bool(token) and hmac.compare_digest(stored, _hash(token))


def validate_first_admin(email: str, password: str, full_name: str = "") -> None:
    """ValidationError with the rule's message (never the password) when the input is refused."""
    validate_email(email)
    validate_password(password, user=get_user_model()(email=email, full_name=full_name))


def create_first_admin(email: str, password: str, full_name: str = ""):
    """Account one: an active superuser holding the administrator role. The caller is responsible
    for the 'no admin yet' decision; this re-checks it inside the transaction, which counts."""
    user_model = get_user_model()
    with transaction.atomic():
        if not needed():
            raise SetupSealed("an active superuser already exists")
        if not Permission.objects.exists():
            sync_catalog()
        # Both idempotent: administrator exists and holds every permission.
        services.ensure_system_roles()
        services.recompute_administrator()
        user = user_model.objects.create_superuser(email, password, full_name=full_name)
        services.assign_role(
            actor=None, user=user, role=Role.objects.get(slug=services.ADMINISTRATOR)
        )
        log_activity("users.user.bootstrapped", target=user)
    return user


def complete(token: str, email: str, password: str, full_name: str = ""):
    """The wizard's one write. Sealed, token and input are all checked before any row changes, and
    the account and the token's clearing share one transaction."""
    if not needed():
        raise SetupSealed("setup is already complete")
    if not verify_token(token):
        raise InvalidSetupToken("the setup token is wrong or was never issued")
    validate_first_admin(email, password, full_name)  # ValidationError propagates
    with transaction.atomic():
        user = create_first_admin(email, password, full_name)
        reset("rbac.setup.token_hash", reason="setup completed")
    return user


__all__ = [
    "InvalidSetupToken",
    "register",
    "SetupError",
    "SetupSealed",
    "complete",
    "create_first_admin",
    "issue_token",
    "needed",
    "validate_first_admin",
    "verify_token",
]
