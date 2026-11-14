"""The users module's notification purposes (BUILD_ORDER 7.7): the three auth emails. All are
mandatory (a security notice: no matrix, no opt-out) and token-bearing (the single-use link lives
in memory only and is never test-routed in production). Registered from UsersConfig.ready()."""

from core.registry import NotificationPurpose

SAMPLE_TOKEN = "TEST-TOKEN"

PURPOSES = (
    NotificationPurpose(
        code="users.password_reset",
        label="Password reset",
        owner_module="users",
        description="A single-use link to choose a new password.",
        default_channels=("email",),
        preview="users.notifications.password_reset_preview",
        template="users/email/password_reset",
        mandatory=True,
        carries_token=True,
        level="action",
    ),
    NotificationPurpose(
        code="users.invitation",
        label="Invitation",
        owner_module="users",
        description="An invitation to sign in, with a single-use link to choose a password.",
        default_channels=("email",),
        recipients="users.notifications.invitation_recipients",
        preview="users.notifications.invitation_preview",
        template="users/email/invitation",
        mandatory=True,
        carries_token=True,
        level="action",
    ),
    NotificationPurpose(
        code="users.account_setup",
        label="Account setup",
        owner_module="users",
        description="A single-use link for a new account's owner to choose a password.",
        default_channels=("email",),
        preview="users.notifications.account_setup_preview",
        template="users/email/account_setup",
        mandatory=True,
        carries_token=True,
        level="action",
    ),
)


def invitation_recipients(object_ref: str, context: dict) -> list[str]:
    """The invitee's address comes from the invitation itself, never from the caller."""
    from .models import Invitation

    _, _, pk = object_ref.partition(":")
    invitation = Invitation.objects.filter(pk=pk).first() if pk.isdigit() else None
    return [invitation.email] if invitation is not None else []


def password_reset_preview() -> dict:
    return {"link_path": "reset-password", "token": SAMPLE_TOKEN, "minutes": 60}


def invitation_preview() -> dict:
    return {
        "link_path": "accept-invitation",
        "token": SAMPLE_TOKEN,
        "invitation_email": "invitee@example.com",
        "invited_by_email": "admin@example.com",
        "days": 7,
    }


def account_setup_preview() -> dict:
    return {"link_path": "reset-password", "token": SAMPLE_TOKEN, "days": 7}
