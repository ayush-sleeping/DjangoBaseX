from django.urls import path

from .api.audit import ActivityLogViewSet
from .api.crypto import CryptoStatusView
from .api.flags import FlagDetailView, FlagListView
from .api.lookups import LookupListView, LookupWriteView
from .api.settings import SettingDetailView, SettingListView, SettingResetView
from .api.webhooks import WebhookEndpointViewSet
from .views import (
    ComponentsView,
    CspReportView,
    LiveView,
    NavigationView,
    PublicConfigView,
    ReadyView,
)
from .webhooks.inbound import InboundWebhookView

app_name = "core"

urlpatterns = [
    path("health/", LiveView.as_view(), name="health"),  # the alias every probe already uses
    path("health/live/", LiveView.as_view(), name="health-live"),
    path("health/ready/", ReadyView.as_view(), name="health-ready"),
    path("health/components/", ComponentsView.as_view(), name="health-components"),
    path("public/config/", PublicConfigView.as_view(), name="public-config"),
    path("public/csp-report/", CspReportView.as_view(), name="csp-report"),
    path("me/navigation/", NavigationView.as_view(), name="navigation"),
    # CONFIGURATION.md § 9.8. No create, no delete: a key exists because code declared it.
    path("core/settings/", SettingListView.as_view(), name="settings"),
    path("core/settings/<str:key>/", SettingDetailView.as_view(), name="setting"),
    path("core/settings/<str:key>/reset/", SettingResetView.as_view(), name="setting-reset"),
    path("core/flags/", FlagListView.as_view(), name="flags"),
    path("core/flags/<str:key>/", FlagDetailView.as_view(), name="flag"),
    # § 4.6: GET only. There is no write route on the log, and ActivityLogViewSet defines none.
    path("core/activity/", ActivityLogViewSet.as_view({"get": "list"}), name="activity"),
    path(
        "core/activity/export/",
        ActivityLogViewSet.as_view({"get": "export"}),
        name="activity-export",
    ),
    path("system/crypto/", CryptoStatusView.as_view(), name="crypto-status"),
    path("core/lookups/", LookupListView.as_view(), name="lookups"),
    path("core/lookups/<str:set_key>/values/", LookupWriteView.as_view(), name="lookup-add"),
    path(
        "core/lookups/<str:set_key>/values/<slug:key>/",
        LookupWriteView.as_view(),
        name="lookup-value",
    ),
    # § 16: platform-owned webhook endpoints. The secret is in the create and rotate responses only.
    path(
        "webhooks/endpoints/",
        WebhookEndpointViewSet.as_view({"get": "list", "post": "create"}),
        name="webhook-endpoints",
    ),
    path(
        "webhooks/events/",
        WebhookEndpointViewSet.as_view({"get": "catalogue"}),
        name="webhook-events",
    ),
    path(
        "webhooks/endpoints/<uuid:public_id>/",
        WebhookEndpointViewSet.as_view(
            {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}
        ),
        name="webhook-endpoint",
    ),
    path(
        "webhooks/endpoints/<uuid:public_id>/rotate-secret/",
        WebhookEndpointViewSet.as_view({"post": "rotate_secret"}),
        name="webhook-rotate-secret",
    ),
    path(
        "webhooks/endpoints/<uuid:public_id>/send-test/",
        WebhookEndpointViewSet.as_view({"post": "send_test"}),
        name="webhook-send-test",
    ),
    path(
        "webhooks/endpoints/<uuid:public_id>/deliveries/",
        WebhookEndpointViewSet.as_view({"get": "deliveries"}),
        name="webhook-deliveries",
    ),
    path(
        "webhooks/endpoints/<uuid:public_id>/deliveries/<slug:delivery_id>/redeliver/",
        WebhookEndpointViewSet.as_view({"post": "redeliver"}),
        name="webhook-redeliver",
    ),
    # § 17: public by declaration (core.routes.CORE_PUBLIC_ROUTES).
    path(
        "hooks/<slug:provider>/<slug:ingress_token>/",
        InboundWebhookView.as_view(),
        name="inbound-webhook",
    ),
]
