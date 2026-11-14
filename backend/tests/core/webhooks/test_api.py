"""/api/webhooks/: permissions, the secret shown once, validation on write, audit."""

import json
import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import WebhookDelivery
from core.webhooks import service
from tests.core.webhooks.conftest import URL, client_with

pytestmark = pytest.mark.django_db

CREATED = "users.user.created"
VIEW, MANAGE = "core.webhooks.view", "core.webhooks.manage"
LIST = "core:webhook-endpoints"


def body(**over):
    return {"name": "CRM", "url": URL, "events": [CREATED]} | over


def create(client, **over):
    return client.post(reverse(LIST), body(**over), format="json")


@pytest.fixture
def admin(public_dns):
    return client_with(VIEW, MANAGE)


def test_create_returns_the_secret_once_and_never_again(admin):
    response = create(admin)
    assert response.status_code == 201
    created = response.json()
    secret = created["secret"]
    assert secret.startswith("test_product_whsec_")
    endpoint_id = created["id"]
    seen = [
        admin.get(reverse(LIST)),
        admin.get(reverse("core:webhook-endpoint", args=[endpoint_id])),
        admin.patch(
            reverse("core:webhook-endpoint", args=[endpoint_id]), {"name": "New"}, format="json"
        ),
        admin.get(reverse("core:webhook-deliveries", args=[endpoint_id])),
    ]
    for response in seen:
        text = json.dumps(response.json())
        assert secret not in text and "ciphertext" not in text
        assert '"secret"' not in text  # no key of that name in any rendering


def test_no_serializer_that_renders_an_endpoint_has_a_secret_field():
    from core.webhooks.serializers import WebhookDeliverySerializer, WebhookEndpointSerializer

    for serializer in (WebhookEndpointSerializer, WebhookDeliverySerializer):
        assert not [f for f in serializer().fields if f == "secret" or "cipher" in f]


def test_the_secret_is_stored_encrypted(admin):
    from core.models import WebhookEndpoint

    secret = create(admin).json()["secret"]
    stored = WebhookEndpoint.objects.get().secret_ciphertext
    assert secret not in stored and stored


def test_rotate_returns_a_new_secret_once_and_keeps_the_old_one_for_the_overlap(admin):
    created = create(admin).json()
    response = admin.post(reverse("core:webhook-rotate-secret", args=[created["id"]]))
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["secret"] != created["secret"] and rotated["previous_secret_expires_at"]
    from core.models import WebhookEndpoint

    assert service.live_secrets(WebhookEndpoint.objects.get()) == [
        rotated["secret"],
        created["secret"],
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "https://169.254.169.254/latest",
        "https://[::1]/x",
        "https://user:pw@hooks.example.com/x",
        "ftp://hooks.example.com/x",
        "https://10.1.2.3/x",
    ],
)
def test_private_loopback_and_malformed_urls_are_refused_at_write(admin, url):
    response = create(admin, url=url)
    assert response.status_code == 400 and "url" in response.json()["error"]["details"]


def test_localhost_is_refused_by_real_resolution():
    client = client_with(VIEW, MANAGE)  # no public_dns: the real resolver answers 127.0.0.1
    assert create(client, url="https://localhost/x").status_code == 400


def test_a_hostname_that_resolves_privately_is_refused_at_write(admin, monkeypatch):
    import ipaddress

    monkeypatch.setattr(service, "resolver", lambda host, port: [ipaddress.ip_address("10.0.0.9")])
    assert create(admin).status_code == 400


def test_https_only_in_production_unless_allowed(admin, production, setting_override):
    assert create(admin, url="http://hooks.example.com/in").status_code == 400
    setting_override("webhooks.delivery.allow_http", True)
    assert create(admin, url="http://hooks.example.com/in").status_code == 201


@pytest.mark.parametrize(
    "events", [[], ["users.user.exploded"], ["users.user.*"], ["*"], [CREATED, "nope.x.y"]]
)
def test_subscriptions_are_validated_against_the_catalogue(admin, events):
    response = create(admin, events=events)
    assert response.status_code == 400 and "events" in response.json()["error"]["details"]


@pytest.mark.parametrize(
    "name",
    [
        "Host",
        "Authorization",
        "Cookie",
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Test-Product-Signature",
        "X-Test-Product-Timestamp",
        "Content-Length",
        "User-Agent",
        "Bad Name",
    ],
)
def test_forbidden_custom_headers_are_refused(admin, name):
    response = create(admin, custom_headers={name: "x"})
    assert response.status_code == 400 and "custom_headers" in response.json()["error"]["details"]


def test_header_values_cannot_inject_lines(admin):
    assert create(admin, custom_headers={"X-Tenant": "a\r\nHost: evil"}).status_code == 400


def test_timeout_defaults_and_is_capped(admin):
    assert create(admin).json()["timeout_seconds"] == 10
    assert create(admin, timeout_seconds=31).status_code == 400
    assert create(admin, timeout_seconds=30).json()["timeout_seconds"] == 30


def test_catalogue_endpoint_lists_external_events(admin):
    events = {item["event"] for item in admin.get(reverse("core:webhook-events")).json()}
    assert events == {CREATED, "users.user.deactivated"}


def test_audit_rows_for_create_repoint_rotate_delete(admin, audit_rows):
    created = create(admin).json()
    detail = reverse("core:webhook-endpoint", args=[created["id"]])
    admin.patch(detail, {"name": "Renamed"}, format="json")
    admin.patch(detail, {"url": "https://elsewhere.example.com/in"}, format="json")
    admin.post(reverse("core:webhook-rotate-secret", args=[created["id"]]))
    assert admin.delete(detail).status_code == 204
    actions = [r.action for r in audit_rows() if r.action.startswith("core.webhook.")]
    assert actions == [
        "core.webhook.created",
        "core.webhook.repointed",  # a rename alone is not audited; a new URL redirects data
        "core.webhook.secret_rotated",
        "core.webhook.deleted",
    ]
    text = json.dumps([[r.changes, r.meta] for r in audit_rows()], default=str)
    assert created["secret"] not in text and "whsec" not in text


def test_send_test_and_redeliver_through_the_api(admin, network, run_outbox):
    created = create(admin).json()
    sent = admin.post(reverse("core:webhook-send-test", args=[created["id"]]))
    assert sent.status_code == 202 and sent.json()["is_test"] is True
    run_outbox()
    listing = admin.get(reverse("core:webhook-deliveries", args=[created["id"]])).json()
    assert listing[0]["status"] == "delivered"
    again = admin.post(reverse("core:webhook-redeliver", args=[created["id"], listing[0]["id"]]))
    assert again.status_code == 202 and again.json()["id"] == listing[0]["id"]
    assert (
        admin.post(
            reverse("core:webhook-redeliver", args=[created["id"], listing[0]["id"]])
        ).status_code
        == 409
    )  # still pending
    assert WebhookDelivery.objects.count() == 1


def test_redeliver_of_an_unknown_delivery_is_404(admin):
    created = create(admin).json()
    assert (
        admin.post(reverse("core:webhook-redeliver", args=[created["id"], "whd_nope"])).status_code
        == 404
    )


def test_deleting_an_endpoint_removes_its_deliveries(admin, network, run_outbox):
    created = create(admin).json()
    admin.post(reverse("core:webhook-send-test", args=[created["id"]]))
    run_outbox()
    admin.delete(reverse("core:webhook-endpoint", args=[created["id"]]))
    assert WebhookDelivery.objects.count() == 0


# --- permissions: every route, every denial ------------------------------------------------------

SOME = str(uuid.uuid4())
ROUTES = [
    ("get", "core:webhook-endpoints", [], VIEW),
    ("post", "core:webhook-endpoints", [], MANAGE),
    ("get", "core:webhook-events", [], VIEW),
    ("get", "core:webhook-endpoint", [SOME], VIEW),
    ("patch", "core:webhook-endpoint", [SOME], MANAGE),
    ("delete", "core:webhook-endpoint", [SOME], MANAGE),
    ("post", "core:webhook-rotate-secret", [SOME], MANAGE),
    ("post", "core:webhook-send-test", [SOME], MANAGE),
    ("get", "core:webhook-deliveries", [SOME], VIEW),
    ("post", "core:webhook-redeliver", [SOME, "whd_x"], MANAGE),
]


@pytest.mark.parametrize("method, name, args, needs", ROUTES)
def test_every_route_refuses_anonymous_and_the_wrong_permission(method, name, args, needs):
    url = reverse(name, args=args)
    assert getattr(APIClient(), method)(url, {}, format="json").status_code == 401
    assert getattr(client_with(), method)(url, {}, format="json").status_code == 403
    other = MANAGE if needs == VIEW else VIEW
    # view does not grant manage; and manage does not grant view (no implicit ladder)
    assert getattr(client_with(other), method)(url, {}, format="json").status_code == 403
    allowed = getattr(client_with(needs), method)(url, {}, format="json").status_code
    assert allowed not in (401, 403)
