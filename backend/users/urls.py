from django.urls import path

from .views import LoginView, LogoutView, MeView, RefreshView, RevokeOtherSessionsView

app_name = "users"

# Mounted under /api/ by config/urls.py. Login and refresh are public: core.routes.PUBLIC_ROUTES.
urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path(
        "auth/sessions/revoke-all/", RevokeOtherSessionsView.as_view(), name="sessions-revoke-all"
    ),
]
