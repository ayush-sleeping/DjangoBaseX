"""
/api/auth/ endpoints. Thin: parse, delegate to users.services.auth, respond (AGENTS.md § 3).
Tokens never appear in a response body — only in cookies (AUTH_BLUEPRINT § 6.2 step 10).
"""

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.response import Response

from core.api.views import BaseAPIView

from . import mfa, tokens
from .cookies import clear_auth_cookies, cookie_names, set_auth_cookies
from .reauth import requires_recent_auth
from .serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    MeSerializer,
    MfaConfirmSerializer,
    MfaVerifySerializer,
    PasswordConfirmSerializer,
    ResetPasswordSerializer,
)
from .services import auth, passwords
from .services import mfa as mfa_service
from .throttles import LoginThrottle, MfaThrottle, MfaVerifyThrottle, PasswordResetThrottle

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
INVALID_MFA_CODE = {
    "error": {"code": "invalid_mfa_code", "message": "That code is not valid. Try again."}
}
MFA_TOKEN_INVALID = {
    "error": {
        "code": "mfa_token_invalid",
        "message": "This sign-in step has expired. Enter your password again.",
    }
}
MFA_ALREADY_ENABLED = {
    "error": {"code": "mfa_already_enabled", "message": "Two-factor is already turned on."}
}
MFA_UNAVAILABLE = {
    "error": {"code": "mfa_unavailable", "message": "Two-factor is not configured on this server."}
}
# One body for an unknown, used, expired or inactive-account token.
INVALID_TOKEN = {
    "error": {
        "code": "invalid_token",
        "message": "This reset link is invalid or has expired. Request a new one.",
    }
}


class LoginView(BaseAPIView):
    # Public (core.routes.PUBLIC_ROUTES). No authenticators: a stale access cookie must not turn
    # a sign-in attempt into a 401 before the credentials are even read.
    public = True  # core.routes.PUBLIC_ROUTES
    authentication_classes: list = []
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
        if isinstance(issued, auth.MfaChallenge):
            # No cookies: the mfa_token authorises exactly one call, POST mfa/verify/.
            return Response({"mfa_required": True, "mfa_token": issued.mfa_token})
        response = Response(status=status.HTTP_204_NO_CONTENT)
        set_auth_cookies(response, issued)
        return response


class RefreshView(BaseAPIView):
    # Public: it authenticates by the refresh cookie itself, not by an access token.
    public = True  # core.routes.PUBLIC_ROUTES
    authentication_classes: list = []

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


class LogoutView(BaseAPIView):
    required_permissions = []  # any signed-in user

    def post(self, request):
        auth.logout(request)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)
        return response


class RevokeOtherSessionsView(BaseAPIView):
    required_permissions = []  # any signed-in user

    def post(self, request):
        return Response({"revoked": auth.revoke_other_sessions(request)})


class MeView(BaseAPIView):
    required_permissions = []  # any signed-in user

    def get(self, request):
        return Response(MeSerializer(request.user).data)


class ForgotPasswordView(BaseAPIView):
    # Public. Always 204, whether or not the address exists (§ 6.6).
    public = True  # core.routes.PUBLIC_ROUTES
    authentication_classes: list = []
    throttle_classes = [PasswordResetThrottle]  # 3/hour per address

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        passwords.request_reset(request, serializer.validated_data["email"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResetPasswordView(BaseAPIView):
    # Public: authenticated by the reset token itself.
    public = True  # core.routes.PUBLIC_ROUTES
    authentication_classes: list = []

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


class PasswordConfirmView(BaseAPIView):
    required_permissions = []  # any signed-in user
    throttle_classes = [MfaThrottle]

    def post(self, request):
        serializer = PasswordConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            auth.confirm_password(request, serializer.validated_data["password"])
        except auth.InvalidCredentials:
            return Response(INVALID_CREDENTIALS, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MfaVerifyView(BaseAPIView):
    # Public: authenticated by the password step's mfa_token, which grants nothing else.
    public = True  # core.routes.PUBLIC_ROUTES
    authentication_classes: list = []
    throttle_classes = [MfaVerifyThrottle]

    def post(self, request):
        serializer = MfaVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            issued = mfa_service.verify_login(request, data["mfa_token"], data["code"])
        except mfa_service.InvalidMfaToken:
            return Response(MFA_TOKEN_INVALID, status=status.HTTP_401_UNAUTHORIZED)
        except mfa_service.InvalidCode:
            return Response(INVALID_MFA_CODE, status=status.HTTP_400_BAD_REQUEST)
        except auth.LockedOut:
            return Response(TOO_MANY_ATTEMPTS, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except mfa.MfaNotConfigured:
            return Response(MFA_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        set_auth_cookies(response, issued)
        return response


class MfaSetupView(BaseAPIView):
    required_permissions = []  # any signed-in user
    throttle_classes = [MfaThrottle]

    def post(self, request):
        try:
            return Response(mfa_service.begin_setup(request.user))
        except mfa_service.AlreadyEnabled:
            return Response(MFA_ALREADY_ENABLED, status=status.HTTP_409_CONFLICT)
        except mfa.MfaNotConfigured:
            return Response(MFA_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class MfaConfirmView(BaseAPIView):
    required_permissions = []  # any signed-in user
    throttle_classes = [MfaThrottle]

    def post(self, request):
        serializer = MfaConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            codes = mfa_service.confirm_setup(request.user, serializer.validated_data["code"])
        except mfa_service.InvalidCode:
            return Response(INVALID_MFA_CODE, status=status.HTTP_400_BAD_REQUEST)
        except mfa.MfaNotConfigured:
            return Response(MFA_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"recovery_codes": codes})


class MfaDisableView(BaseAPIView):
    required_permissions = []  # any signed-in user
    permission_classes = [*BaseAPIView.permission_classes, requires_recent_auth("mfa_disable")]
    throttle_classes = [MfaThrottle]

    def post(self, request):
        mfa_service.disable(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
