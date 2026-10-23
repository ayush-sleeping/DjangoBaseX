from django.urls import path

from .api.crypto import CryptoStatusView
from .api.flags import FlagDetailView, FlagListView
from .api.lookups import LookupListView, LookupWriteView
from .api.settings import SettingDetailView, SettingListView, SettingResetView
from .views import ComponentsView, LiveView, NavigationView, PublicConfigView, ReadyView

app_name = "core"

urlpatterns = [
    path("health/", LiveView.as_view(), name="health"),  # the alias every probe already uses
    path("health/live/", LiveView.as_view(), name="health-live"),
    path("health/ready/", ReadyView.as_view(), name="health-ready"),
    path("health/components/", ComponentsView.as_view(), name="health-components"),
    path("public/config/", PublicConfigView.as_view(), name="public-config"),
    path("me/navigation/", NavigationView.as_view(), name="navigation"),
    # CONFIGURATION.md § 9.8. No create, no delete: a key exists because code declared it.
    path("core/settings/", SettingListView.as_view(), name="settings"),
    path("core/settings/<str:key>/", SettingDetailView.as_view(), name="setting"),
    path("core/settings/<str:key>/reset/", SettingResetView.as_view(), name="setting-reset"),
    path("core/flags/", FlagListView.as_view(), name="flags"),
    path("core/flags/<str:key>/", FlagDetailView.as_view(), name="flag"),
    path("system/crypto/", CryptoStatusView.as_view(), name="crypto-status"),
    path("core/lookups/", LookupListView.as_view(), name="lookups"),
    path("core/lookups/<str:set_key>/values/", LookupWriteView.as_view(), name="lookup-add"),
    path(
        "core/lookups/<str:set_key>/values/<slug:key>/",
        LookupWriteView.as_view(),
        name="lookup-value",
    ),
]
