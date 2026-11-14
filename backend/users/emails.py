"""Outbound auth email (AUTH_BLUEPRINT Ch. 18), as notification purposes (BUILD_ORDER 7.7). The
calls name a purpose and the subject; the address comes from the user or the invitation, the link
from FRONTEND_BASE_URL (core.mail.render.frontend_url) and never from the request's Host header.
Each purpose is mandatory and token-bearing: delivered in this process after the commit, the
single-use token held in memory only, never written to the outbox or the delivery log."""

from django.conf import settings

from core.notifications import notify


def send_password_reset(user, raw_token: str) -> None:
    notify(
        "users.password_reset",
        obj=user,
        recipients=[user.pk],
        context={
            "link_path": "reset-password",
            "token": raw_token,
            "minutes": settings.PASSWORD_RESET_TOKEN_LIFETIME // 60,
        },
    )


def send_invitation(invitation, raw_token: str) -> None:
    notify(
        "users.invitation",
        obj=invitation,
        context={
            "link_path": "accept-invitation",
            "token": raw_token,
            "invitation_email": invitation.email,
            "invited_by_email": invitation.invited_by.email if invitation.invited_by else "",
            "days": settings.INVITATION_LIFETIME // 86_400,
        },
    )


def send_account_setup(user, raw_token: str) -> None:
    notify(
        "users.account_setup",
        obj=user,
        recipients=[user.pk],
        context={
            "link_path": "reset-password",
            "token": raw_token,
            "days": settings.PASSWORD_SETUP_TOKEN_LIFETIME // 86_400,
        },
    )
