"""Outbound auth email (AUTH_BLUEPRINT Ch. 18). Every link is built from FRONTEND_BASE_URL — never
from the request's Host header, which would let an attacker point a genuine reset email at their
own server."""

from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_password_reset(user, raw_token: str) -> None:
    _send(
        to=user.email,
        subject="Reset your password",
        template="users/email/password_reset",
        path="reset-password",
        raw_token=raw_token,
        context={"user": user, "minutes": settings.PASSWORD_RESET_TOKEN_LIFETIME // 60},
    )


def send_invitation(invitation, raw_token: str) -> None:
    _send(
        to=invitation.email,
        subject="You have been invited",
        template="users/email/invitation",
        path="accept-invitation",
        raw_token=raw_token,
        context={
            "invitation": invitation,
            "days": settings.INVITATION_LIFETIME // 86_400,
        },
    )


def send_account_setup(user, raw_token: str) -> None:
    _send(
        to=user.email,
        subject="Set your password",
        template="users/email/account_setup",
        path="reset-password",
        raw_token=raw_token,
        context={"user": user, "days": settings.PASSWORD_SETUP_TOKEN_LIFETIME // 86_400},
    )


def _send(*, to, subject, template, path, raw_token, context) -> None:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    context = {**context, "link": f"{base}/{path}?{urlencode({'token': raw_token})}"}
    message = EmailMultiAlternatives(
        subject=subject, body=render_to_string(f"{template}.txt", context), to=[to]
    )
    message.attach_alternative(render_to_string(f"{template}.html", context), "text/html")
    message.send()
