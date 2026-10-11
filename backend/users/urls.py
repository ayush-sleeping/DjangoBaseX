from django.urls import path

from .views import (
    ForgotPasswordView,
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
)

app_name = "users"

# Mounted under /api/ by config/urls.py. Login and refresh are public: core.routes.PUBLIC_ROUTES.
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
]
