from django.urls import path

from .api.flags import FlagDetailView, FlagListView
from .api.settings import SettingDetailView, SettingListView, SettingResetView
from .views import HealthView, NavigationView, PublicConfigView

app_name = "core"

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("public/config/", PublicConfigView.as_view(), name="public-config"),
    path("me/navigation/", NavigationView.as_view(), name="navigation"),
    # CONFIGURATION.md § 9.8. No create, no delete: a key exists because code declared it.
    path("core/settings/", SettingListView.as_view(), name="settings"),
    path("core/settings/<str:key>/", SettingDetailView.as_view(), name="setting"),
    path("core/settings/<str:key>/reset/", SettingResetView.as_view(), name="setting-reset"),
    path("core/flags/", FlagListView.as_view(), name="flags"),
    path("core/flags/<str:key>/", FlagDetailView.as_view(), name="flag"),
]
