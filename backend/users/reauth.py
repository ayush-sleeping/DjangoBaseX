"""
Re-authentication for sensitive actions (AUTH_BLUEPRINT § 6.9, A18).

Lives in `users` for now because it reads users_user_session, and `core` must not import `users`
(Ch. 2). It moves to core.permissions once a session abstraction exists there (1.2 / 9.1).
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

from .models import UserSession


class ReauthRequired(APIException):
    # 423, not 401 or 403: the client must tell "not signed in" and "not allowed" apart from
    # "confirm your password and retry".
    status_code = 423
    default_detail = {
        "error": {"code": "reauth_required", "message": "Confirm your password to continue."}
    }
    default_code = "reauth_required"


class RequiresRecentAuth(BasePermission):
    """
    Off unless `action_key` is in settings.REAUTH_ACTIONS: a control that breaks flows on install
    gets reverted. When on, this session's password must have been confirmed within
    REAUTH_WINDOW_MINUTES. Per session: confirming on a laptop does not unlock a phone.
    """

    action_key = ""

    def has_permission(self, request, view):
        if self.action_key not in settings.REAUTH_ACTIONS:
            return True
        confirmed_at = (
            UserSession.objects.filter(public_id=(request.auth or {}).get("sid"))
            .values_list("password_confirmed_at", flat=True)
            .first()
        )
        window = timedelta(minutes=settings.REAUTH_WINDOW_MINUTES)
        if confirmed_at is not None and timezone.now() - confirmed_at <= window:
            return True
        raise ReauthRequired


def requires_recent_auth(action_key: str) -> type[RequiresRecentAuth]:
    return type(
        f"RequiresRecentAuth[{action_key}]", (RequiresRecentAuth,), {"action_key": action_key}
    )
