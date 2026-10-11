from django.urls import path

from .views import (
    AcceptInvitationView,
    ForgotPasswordView,
    InvitationViewSet,
    LoginView,
    LogoutView,
    MeView,
    MfaConfirmView,
    MfaDisableView,
    MfaSetupView,
    MfaVerifyView,
    PasswordConfirmView,
    RefreshView,
    ResetPasswordView,
    RevokeOtherSessionsView,
    UserViewSet,
)

app_name = "users"

# Mounted under /api/ by config/urls.py. Login and refresh are public: registry.public_routes.
urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/password/forgot/", ForgotPasswordView.as_view(), name="password-forgot"),
    path("auth/password/reset/", ResetPasswordView.as_view(), name="password-reset"),
    path("auth/password/confirm/", PasswordConfirmView.as_view(), name="password-confirm"),
    path("auth/mfa/setup/", MfaSetupView.as_view(), name="mfa-setup"),
    path("auth/mfa/confirm/", MfaConfirmView.as_view(), name="mfa-confirm"),
    path("auth/mfa/verify/", MfaVerifyView.as_view(), name="mfa-verify"),
    path("auth/mfa/disable/", MfaDisableView.as_view(), name="mfa-disable"),
    path(
        "auth/sessions/revoke-all/", RevokeOtherSessionsView.as_view(), name="sessions-revoke-all"
    ),
    path("auth/invitations/accept/", AcceptInvitationView.as_view(), name="invitation-accept"),
    # /api/users/ — the Users module (§ 10.2)
    path("users/", UserViewSet.as_view({"get": "list", "post": "create"}), name="users"),
    path(
        "users/invitations/",
        InvitationViewSet.as_view({"get": "list", "post": "create"}),
        name="invitations",
    ),
    path(
        "users/invitations/<uuid:public_id>/revoke/",
        InvitationViewSet.as_view({"post": "revoke"}),
        name="invitation-revoke",
    ),
    path(
        "users/<uuid:public_id>/",
        UserViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="user",
    ),
    path(
        "users/<uuid:public_id>/deactivate/",
        UserViewSet.as_view({"post": "deactivate"}),
        name="user-deactivate",
    ),
    path(
        "users/<uuid:public_id>/activate/",
        UserViewSet.as_view({"post": "activate"}),
        name="user-activate",
    ),
    path(
        "users/<uuid:public_id>/sessions/revoke/",
        UserViewSet.as_view({"post": "revoke_sessions"}),
        name="user-sessions-revoke",
    ),
]
