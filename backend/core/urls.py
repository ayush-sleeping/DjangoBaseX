from django.urls import path

from .api.audit import ActivityLogViewSet
from .api.consumers import ApiConsumerViewSet
from .api.crypto import CryptoStatusView
from .api.files import FileDownloadView, FileUploadView
from .api.flags import FlagDetailView, FlagListView
from .api.lookups import LookupListView, LookupWriteView
from .api.notifications import (
    NotificationAdminViewSet,
    NotificationPreferenceViewSet,
    NotificationViewSet,
)
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
    # NOTIFICATIONS_AND_ALERTING.md Part A: the bell (own rows), preferences, routes, the matrix.
    path("notifications/", NotificationViewSet.as_view({"get": "list"}), name="notifications"),
    path(
        "notifications/summary/",
        NotificationViewSet.as_view({"get": "summary"}),
        name="notifications-summary",
    ),
    path(
        "notifications/read-all/",
        NotificationViewSet.as_view({"post": "read_all"}),
        name="notifications-read-all",
    ),
    path(
        "notifications/routes/",
        NotificationAdminViewSet.as_view({"get": "routes", "post": "route_create"}),
        name="notification-routes",
    ),
    path(
        "notifications/routes/<int:pk>/",
        NotificationAdminViewSet.as_view({"patch": "route_update", "delete": "route_delete"}),
        name="notification-route",
    ),
    path(
        "notifications/routes/<int:pk>/test/",
        NotificationAdminViewSet.as_view({"post": "route_test"}),
        name="notification-route-test",
    ),
    path(
        "notifications/matrix/",
        NotificationAdminViewSet.as_view({"get": "matrix", "patch": "matrix_update"}),
        name="notification-matrix",
    ),
    path(
        "notifications/purposes/",
        NotificationAdminViewSet.as_view({"get": "purposes"}),
        name="notification-purposes",
    ),
    path(
        "notifications/purposes/<str:code>/test/",
        NotificationAdminViewSet.as_view({"post": "purpose_test"}),
        name="notification-purpose-test",
    ),
    path(
        "notifications/deliveries/",
        NotificationAdminViewSet.as_view({"get": "deliveries"}),
        name="notification-deliveries",
    ),
    path(
        "notifications/<uuid:public_id>/read/",
        NotificationViewSet.as_view({"post": "mark_read"}),
        name="notification-read",
    ),
    path(
        "notifications/<uuid:public_id>/resolve/",
        NotificationViewSet.as_view({"post": "resolve_item"}),
        name="notification-resolve",
    ),
    path(
        "me/notification-preferences/",
        NotificationPreferenceViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="notification-preferences",
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
    # API_PLATFORM § 18-19: sniffed uploads; no public media URL, the download checks the purpose.
    path("files/", FileUploadView.as_view(), name="file-upload"),
    path("files/<uuid:public_id>/", FileDownloadView.as_view(), name="file-download"),
    # ADR-0016: machine callers. Human-only; the plaintext token is in issue/rotate responses only.
    path(
        "consumers/",
        ApiConsumerViewSet.as_view({"get": "list", "post": "create"}),
        name="api-consumers",
    ),
    path(
        "consumers/<uuid:public_id>/",
        ApiConsumerViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="api-consumer",
    ),
    path(
        "consumers/<uuid:public_id>/tokens/",
        ApiConsumerViewSet.as_view({"get": "tokens", "post": "issue_token"}),
        name="api-consumer-tokens",
    ),
    path(
        "consumers/<uuid:public_id>/tokens/<uuid:token_id>/",
        ApiConsumerViewSet.as_view({"patch": "token_scopes"}),
        name="api-consumer-token",
    ),
    path(
        "consumers/<uuid:public_id>/tokens/<uuid:token_id>/rotate/",
        ApiConsumerViewSet.as_view({"post": "rotate_token"}),
        name="api-consumer-token-rotate",
    ),
    path(
        "consumers/<uuid:public_id>/tokens/<uuid:token_id>/revoke/",
        ApiConsumerViewSet.as_view({"post": "revoke_token"}),
        name="api-consumer-token-revoke",
    ),
    # § 17: public by declaration (core.routes.CORE_PUBLIC_ROUTES).
    path(
        "hooks/<slug:provider>/<slug:ingress_token>/",
        InboundWebhookView.as_view(),
        name="inbound-webhook",
    ),
]
