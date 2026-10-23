"""
Re-authentication for sensitive actions (AUTH_BLUEPRINT § 6.9, A18).

Lives in `users` for now because it reads users_user_session, and `core` must not import `users`
(Ch. 2). It moves to core.permissions once a session abstraction exists there (1.2 / 9.1).
"""

from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

from core.settings_registry import Int, StrList, meta
from core.settings_service import resolve

from .models import UserSession

# Every action a view can guard with requires_recent_auth(): the closed vocabulary an operator
# picks from. A view naming an action not listed here fails at import, not silently at runtime.
REAUTH_ACTIONS = ("mfa_disable",)


@dataclass(frozen=True)
class ReauthPolicy:
    """security.reauth.* (CONFIGURATION.md § 9.6). These defaults ARE the code defaults: off for
    every action, because a control that breaks flows on install gets reverted."""

    actions: tuple[str, ...] = field(
        default=(),
        metadata=meta(
            StrList(choices=REAUTH_ACTIONS),
            label="Actions that ask for the password again",
            description=(
                "Each listed action needs the password confirmed within the window below. Listing "
                "more makes a hijacked session less useful, and interrupts real people more."
            ),
            changed_by_event="A security review, or an incident involving a hijacked session",
            used_by=("Two-factor sign-in: disable",),
        ),
    )
    window_minutes: int = field(
        default=15,
        metadata=meta(
            Int(min=1, max=1440),
            label="Minutes a confirmed password counts as recent",
            description=(
                "Longer means fewer password prompts, and a longer time in which a hijacked "
                "session can take a listed action."
            ),
            changed_by_event="Complaints about repeated prompts, or a security review",
            used_by=("Two-factor sign-in: disable",),
        ),
    )


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
    Off unless `action_key` is in security.reauth.actions: a control that breaks flows on install
    gets reverted. When on, this session's password must have been confirmed within
    security.reauth.window_minutes. Per session: confirming on a laptop does not unlock a phone.
    """

    action_key = ""

    def has_permission(self, request, view):
        policy = resolve(ReauthPolicy)
        if self.action_key not in policy.actions:
            return True
        confirmed_at = (
            UserSession.objects.filter(public_id=(request.auth or {}).get("sid"))
            .values_list("password_confirmed_at", flat=True)
            .first()
        )
        window = timedelta(minutes=policy.window_minutes)
        if confirmed_at is not None and timezone.now() - confirmed_at <= window:
            return True
        raise ReauthRequired


def requires_recent_auth(action_key: str) -> type[RequiresRecentAuth]:
    if action_key not in REAUTH_ACTIONS:
        raise ValueError(f"{action_key!r} is not in users.reauth.REAUTH_ACTIONS; add it there")
    return type(
        f"RequiresRecentAuth[{action_key}]", (RequiresRecentAuth,), {"action_key": action_key}
    )
