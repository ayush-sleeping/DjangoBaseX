"""Outbound auth email (AUTH_BLUEPRINT Ch. 18). Every link is built from FRONTEND_BASE_URL — never
from the request's Host header, which would let an attacker point a genuine reset email at their
own server."""

from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_password_reset(user, raw_token: str) -> None:
    link = (
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/reset-password?{urlencode({'token': raw_token})}"
    )
    context = {
        "user": user,
        "link": link,
        "minutes": settings.PASSWORD_RESET_TOKEN_LIFETIME // 60,
    }
    message = EmailMultiAlternatives(
        subject="Reset your password",
        body=render_to_string("users/email/password_reset.txt", context),
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string("users/email/password_reset.html", context), "text/html"
    )
    message.send()
