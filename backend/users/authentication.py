"""CookieJWTAuthentication — the DRF authenticator for /api/ requests (AUTH_BLUEPRINT § 6.4)."""

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS

from . import tokens
from .cookies import CSRF_HEADER, cookie_names
from .models import User


class CookieJWTAuthentication(BaseAuthentication):
    """
    1. read the access cookie   2. verify signature, expiry and type   3. load an active user
    4. confirm the session row is live   5. on unsafe methods, check the session-bound CSRF token

    No access cookie means anonymous (None), so permissions decide. A cookie that is present but
    invalid is a 401, which tells the frontend to refresh and retry once.
    Machine callers do not come through here (API_PLATFORM.md § 7).
    """

    def authenticate(self, request):
        token = request.COOKIES.get(cookie_names().access)
        if not token:
            return None
        try:
            claims = tokens.decode(token, tokens.ACCESS)
        except tokens.TokenError as exc:
            raise AuthenticationFailed("Session expired or invalid.") from exc

        user = User.objects.filter(public_id=claims["sub"]).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed("Session expired or invalid.")
        if not tokens.session_is_live(claims["sid"], user):
            raise AuthenticationFailed("Session expired or invalid.")

        if request.method not in SAFE_METHODS and not tokens.csrf_matches(
            claims["sid"], request.META.get(CSRF_HEADER)
        ):
            raise PermissionDenied("CSRF token missing or incorrect.")
        return (user, claims)

    def authenticate_header(self, request):
        # Present so DRF answers an anonymous caller 401 rather than 403.
        return 'Cookie realm="api"'
