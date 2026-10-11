"""
/api/auth/ endpoints. Thin: parse, delegate to users.services.auth, respond (AGENTS.md § 3).
Tokens never appear in a response body — only in cookies (AUTH_BLUEPRINT § 6.2 step 10).
"""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import tokens
from .cookies import clear_auth_cookies, cookie_names, set_auth_cookies
from .serializers import LoginSerializer, MeSerializer
from .services import auth

# One body for wrong password, unknown address and inactive account, so login is not an oracle.
INVALID_CREDENTIALS = {
    "error": {"code": "invalid_credentials", "message": "Email or password is incorrect."}
}
SESSION_ENDED = {
    "error": {"code": "session_ended", "message": "Your session has ended. Sign in again."}
}


class LoginView(APIView):
    # Public (core.routes.PUBLIC_ROUTES). No authenticators: a stale access cookie must not turn
    # a sign-in attempt into a 401 before the credentials are even read.
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            issued = auth.login(request, **serializer.validated_data)
        except auth.InvalidCredentials:
            return Response(INVALID_CREDENTIALS, status=status.HTTP_401_UNAUTHORIZED)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        set_auth_cookies(response, issued)
        return response


class RefreshView(APIView):
    # Public: it authenticates by the refresh cookie itself, not by an access token.
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get(cookie_names().refresh)
        try:
            if not refresh_token:
                raise tokens.TokenError("no refresh cookie")
            issued = auth.refresh(request, refresh_token)
        except tokens.TokenError:
            response = Response(SESSION_ENDED, status=status.HTTP_401_UNAUTHORIZED)
            clear_auth_cookies(response)
            return response
        response = Response(status=status.HTTP_204_NO_CONTENT)
        set_auth_cookies(response, issued)
        return response


class LogoutView(APIView):
    def post(self, request):
        auth.logout(request)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)
        return response


class RevokeOtherSessionsView(APIView):
    def post(self, request):
        return Response({"revoked": auth.revoke_other_sessions(request)})


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)
