"""
/api/auth/ endpoints. Thin: parse, delegate to users.services.auth, respond (AGENTS.md § 3).
Tokens never appear in a response body — only in cookies (AUTH_BLUEPRINT § 6.2 step 10).

The /api/users/ section (UserViewSet onward) is the reference module every later module copies
(BUILD_ORDER 1.5): a BaseViewSet with required_permissions per action, get_queryset() through
visible_to() so an invisible row is a 404, validate-only serializers, one services call per write.
"""

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api.errors import error_response, from_exception, invalid_response
from core.api.views import BaseAPIView
from core.api.viewsets import BaseViewSet

from . import mfa, tokens
from .cookies import clear_auth_cookies, cookie_names, set_auth_cookies
from .models import Invitation, User
from .reauth import requires_recent_auth
from .serializers import (
    AcceptInvitationSerializer,
    DeactivateSerializer,
    ForgotPasswordSerializer,
    InvitationCreateSerializer,
    InvitationSerializer,
    LoginSerializer,
    MeSerializer,
    MfaConfirmSerializer,
    MfaVerifySerializer,
    PasswordConfirmSerializer,
    ResetPasswordSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from .services import auth, invitations, passwords
from .services import mfa as mfa_service
from .services import users as users_service
from .throttles import (
    InvitationAcceptThrottle,
    LoginThrottle,
    MfaThrottle,
    MfaVerifyThrottle,
    PasswordResetThrottle,
)

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
    # Public (registry.public_routes). No authenticators: a stale access cookie must not turn
    # a sign-in attempt into a 401 before the credentials are even read.
    public = True  # registry.public_routes
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
    public = True  # registry.public_routes
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
    public = True  # registry.public_routes
    authentication_classes: list = []
    throttle_classes = [PasswordResetThrottle]  # 3/hour per address

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        passwords.request_reset(request, serializer.validated_data["email"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResetPasswordView(BaseAPIView):
    # Public: authenticated by the reset token itself.
    public = True  # registry.public_routes
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
    public = True  # registry.public_routes
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


# --- /api/users/ ---------------------------------------------------------------------------------


def role_model():
    return apps.get_model("rbac", "Role")  # by string: users never imports rbac (Ch. 2)


class UserViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = UserSerializer
    required_permissions = {
        "list": ["users.users.view"],
        "retrieve": ["users.users.view"],
        "create": ["users.users.create"],
        "partial_update": ["users.users.update"],
        "deactivate": ["users.users.deactivate"],
        "activate": ["users.users.deactivate"],
        "revoke_sessions": ["users.sessions.revoke"],
    }

    def get_queryset(self):
        queryset = (
            User.objects.visible_to(self.request.user)
            .prefetch_related(
                Prefetch("user_roles", queryset=_user_roles_with_role()), "mfa_devices"
            )
            .order_by("email", "pk")
        )
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(email__icontains=search) | Q(full_name__icontains=search))
        return queryset

    def _fresh(self, user):
        return UserSerializer(self.get_queryset().get(pk=user.pk)).data

    def create(self, request):
        serializer = UserCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        user = users_service.create_user(actor=request.user, **serializer.validated_data)
        return Response(self._fresh(user), status=status.HTTP_201_CREATED)

    def partial_update(self, request, public_id=None):
        user = self.get_object()
        serializer = UserUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        users_service.update_user(actor=request.user, user=user, **serializer.validated_data)
        return Response(self._fresh(user))

    @action(detail=True, methods=["post"])
    def deactivate(self, request, public_id=None):
        user = self.get_object()
        serializer = DeactivateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            users_service.deactivate(
                actor=request.user, user=user, reason=serializer.validated_data["reason"]
            )
        except users_service.UsersError as exc:
            return from_exception(exc, status.HTTP_409_CONFLICT)
        return Response(self._fresh(user))

    @action(detail=True, methods=["post"])
    def activate(self, request, public_id=None):
        user = users_service.activate(actor=request.user, user=self.get_object())
        return Response(self._fresh(user))

    @action(detail=True, methods=["post"], url_path="sessions/revoke")
    def revoke_sessions(self, request, public_id=None):
        count = users_service.revoke_sessions(actor=request.user, user=self.get_object())
        return Response({"revoked": count})


def _user_roles_with_role():
    user_role = apps.get_model("rbac", "UserRole")
    return user_role.objects.select_related("role").order_by("role__name")


class InvitationViewSet(BaseViewSet, mixins.ListModelMixin):
    serializer_class = InvitationSerializer
    required_permissions = {
        "list": ["users.invitations.send"],
        "create": ["users.invitations.send"],
        "revoke": ["users.invitations.send"],
    }

    def get_queryset(self):
        return Invitation.objects.select_related("role", "invited_by").order_by(
            "-created_at", "-pk"
        )

    def create(self, request):
        serializer = InvitationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        role = get_object_or_404(role_model(), public_id=serializer.validated_data["role"])
        try:
            invitation = invitations.invite(
                actor=request.user, email=serializer.validated_data["email"], role=role
            )
        except invitations.ElevatedRequiresSuperuser as exc:
            return from_exception(exc, status.HTTP_403_FORBIDDEN)
        except invitations.InvitationError as exc:
            return from_exception(exc, status.HTTP_409_CONFLICT)
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revoke(self, request, public_id=None):
        try:
            invitation = invitations.revoke(actor=request.user, invitation=self.get_object())
        except invitations.NotPending as exc:
            return from_exception(exc, status.HTTP_409_CONFLICT)
        return Response(InvitationSerializer(invitation).data)


class AcceptInvitationView(BaseAPIView):
    # Public (registry.public_routes): authenticated by the invitation token itself.
    public = True
    authentication_classes: list = []
    throttle_classes = [InvitationAcceptThrottle]

    def post(self, request):
        serializer = AcceptInvitationSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        data = serializer.validated_data
        try:
            issued = invitations.accept(request, data["token"], data["password"], data["full_name"])
        except invitations.InvalidInvitationToken:
            return error_response(
                "invalid_token",
                "This invitation is invalid or has expired. Ask for a new one.",
                status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as exc:
            return error_response(
                "invalid_password",
                "Choose a different password.",
                status.HTTP_400_BAD_REQUEST,
                details=list(exc.messages),
            )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        set_auth_cookies(response, issued)
        return response
