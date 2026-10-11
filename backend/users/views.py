"""
/api/auth/ endpoints. Thin: parse, delegate to users.services.auth, respond (AGENTS.md § 3).
Tokens never appear in a response body — only in cookies (AUTH_BLUEPRINT § 6.2 step 10).
"""

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import tokens
from .cookies import clear_auth_cookies, cookie_names, set_auth_cookies
from .serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    MeSerializer,
    ResetPasswordSerializer,
)
from .services import auth, passwords
from .throttles import LoginThrottle, PasswordResetThrottle

# One body for wrong password, unknown address and inactive account, so login is not an oracle.
INVALID_CREDENTIALS = {
    "error": {"code": "invalid_credentials", "message": "Email or password is incorrect."}
}
SESSION_ENDED = {
    "error": {"code": "session_ended", "message": "Your session has ended. Sign in again."}
}
TOO_MANY_ATTEMPTS = {
    "error": {"code": "too_many_attempts", "message": "Too many attempts. Try again later."}
}
# One body for an unknown, used, expired or inactive-account token.
INVALID_TOKEN = {
    "error": {
        "code": "invalid_token",
        "message": "This reset link is invalid or has expired. Request a new one.",
    }
}


class LoginView(APIView):
    # Public (core.routes.PUBLIC_ROUTES). No authenticators: a stale access cookie must not turn
    # a sign-in attempt into a 401 before the credentials are even read.
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]  # step 1: 5/min per (address, IP) pair

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            issued = auth.login(request, **serializer.validated_data)
        except auth.InvalidCredentials:
            return Response(INVALID_CREDENTIALS, status=status.HTTP_401_UNAUTHORIZED)
        except auth.LockedOut:
            return Response(TOO_MANY_ATTEMPTS, status=status.HTTP_429_TOO_MANY_REQUESTS)
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


class ForgotPasswordView(APIView):
    # Public. Always 204, whether or not the address exists (§ 6.6).
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]  # 3/hour per address

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        passwords.request_reset(request, serializer.validated_data["email"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResetPasswordView(APIView):
    # Public: authenticated by the reset token itself.
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = serializer.validated_data
            passwords.perform_reset(request, data["token"], data["password"])
        except passwords.InvalidResetToken:
            return Response(INVALID_TOKEN, status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as exc:
            body = {
                "error": {
                    "code": "invalid_password",
                    "message": "Choose a different password.",
                    "details": list(exc.messages),
                }
            }
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)  # every session just ended, this browser's included
        return response
