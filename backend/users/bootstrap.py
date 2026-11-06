"""
The users app's sections of GET /api/me/bootstrap/ (FRONTEND_PLATFORM.md § 7): who is signed in,
and when the session ends. Both are essential: without them the shell cannot render, so a failure
here fails the response and the frontend fails closed.

core.bootstrap owns the engine and core's sections; this module composes them, because users
depends on core and never the other way round.
"""

from datetime import timedelta

from django.conf import settings

from core.bootstrap import CORE_CONTRIBUTORS, Contributor

from .models import UserSession
from .serializers import BootstrapUserSerializer


def _user(request) -> dict:
    return BootstrapUserSerializer(request.user).data


def _session(request) -> dict:
    """The absolute expiry and the idle deadline of the session behind this access token, so the
    shell can warn before either. The access token's own expiry is not here: a 401 refreshes it."""
    session = UserSession.objects.only("expires_at", "last_seen_at").get(
        public_id=request.auth["sid"], user=request.user
    )
    idle = session.last_seen_at + timedelta(seconds=settings.REFRESH_IDLE_LIFETIME)
    return {
        "expires_at": session.expires_at.isoformat(),
        "idle_expires_at": min(idle, session.expires_at).isoformat(),
    }


CONTRIBUTORS: tuple[Contributor, ...] = (
    Contributor("user", _user, essential=True),
    Contributor("session", _session, essential=True),
    *CORE_CONTRIBUTORS,
)
