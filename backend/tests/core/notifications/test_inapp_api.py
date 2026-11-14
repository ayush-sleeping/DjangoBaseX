"""The in_app store and its API (NOTIFICATIONS_AND_ALERTING.md § 8)."""

import pytest
from rest_framework.test import APIClient

from core.models import Notification
from core.notifications import digest, inapp, resolve
from tests.core.webhooks.conftest import client_with
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def put(user, ref="orders.order:1", **kw):
    return inapp.upsert(
        recipient_id=user.pk, purpose="tests.plain", level="info", title="T", object_ref=ref, **kw
    )


def test_one_open_row_per_recipient_purpose_and_object():
    user = UserFactory()
    first, second = (
        put(user, title2 if (title2 := None) else None) if False else put(user),
        put(user),
    )
    assert first.pk == second.pk and Notification.objects.count() == 1
    other = UserFactory()
    put(other)
    assert Notification.objects.count() == 2  # another recipient has their own row
    put(user, ref="orders.order:2")
    assert Notification.objects.count() == 3


def test_resolving_closes_every_recipients_row_and_a_new_run_opens_a_fresh_one():
    a, b = UserFactory(), UserFactory()
    put(a), put(b)
    assert resolve("orders.order:1", by=a, note="done") == 2
    assert not Notification.objects.filter(resolved_at__isnull=True).exists()
    put(a)  # the subject needs attention again: a new open row is allowed
    assert Notification.objects.filter(resolved_at__isnull=True).count() == 1


def test_read_state_is_per_user():
    a, b = UserFactory(), UserFactory()
    row_a, row_b = put(a), put(b)
    response = client_for(a).post(f"/api/notifications/{row_a.public_id}/read/")
    assert response.status_code == 200 and response.json()["read"] is True
    row_b.refresh_from_db()
    assert row_b.read_at is None


def test_another_users_notification_is_a_404():
    a, b = UserFactory(), UserFactory()
    row_b = put(b)
    client = client_for(a)
    assert client.post(f"/api/notifications/{row_b.public_id}/read/").status_code == 404
    assert client.post(f"/api/notifications/{row_b.public_id}/resolve/").status_code == 404
    assert client.get("/api/notifications/").json() == []


def test_resolve_through_the_api_is_shared():
    a, b = UserFactory(), UserFactory()
    row_a, row_b = put(a), put(b)
    assert client_for(a).post(f"/api/notifications/{row_a.public_id}/resolve/").status_code == 200
    row_b.refresh_from_db()
    assert row_b.resolved_at is not None


def test_the_polled_summary_counts_unread_and_open_actions():
    user = UserFactory()
    put(user)
    inapp.upsert(
        recipient_id=user.pk, purpose="tests.plain", level="action", title="Act", object_ref="x:1"
    )
    client = client_for(user)
    body = client.get("/api/notifications/summary/").json()
    assert body["unread"] == 2 and body["open_actions"] == 1
    client.post("/api/notifications/read-all/", {"up_to_id": body["latest_id"]}, format="json")
    assert client.get("/api/notifications/summary/").json()["unread"] == 0


def test_read_all_respects_up_to_id():
    user = UserFactory()
    old = put(user)
    new = put(user, ref="x:2")
    client_for(user).post("/api/notifications/read-all/", {"up_to_id": old.pk}, format="json")
    old.refresh_from_db(), new.refresh_from_db()
    assert old.read_at is not None and new.read_at is None


def test_digest_resurface_keeps_the_id_and_shrinking_does_not_resurface():
    user = UserFactory()
    row = digest("tests.plain", user.pk, "sync:1", "3 changes", 3)
    inapp.mark_read(user, row)
    again = digest("tests.plain", user.pk, "sync:1", "12 changes", 12)
    assert again.pk == row.pk and again.count == 12 and again.read_at is None
    inapp.mark_read(user, again)
    smaller = digest("tests.plain", user.pk, "sync:1", "2 changes", 2, resurface=False)
    assert smaller.read_at is not None


@pytest.mark.parametrize("url", ["https://evil.example/x", "//evil.example", "javascript:1", "x"])
def test_off_site_urls_are_rejected(url):
    assert not inapp.valid_url(url)
    assert inapp.valid_url("/billing/invoices/42")


def test_admin_routes_need_the_permission_and_are_audited():
    plain = client_with()
    assert plain.get("/api/notifications/routes/").status_code == 403
    admin = client_with("core.notifications.view", "core.notifications.manage")
    # a user purpose is not routable; a broadcast purpose is
    bad = admin.post(
        "/api/notifications/routes/",
        {
            "purpose": "users.password_reset",
            "channel": "email",
            "target": {"addresses": ["a@b.co"]},
        },
        format="json",
    )
    assert bad.status_code == 400
    ok = admin.post(
        "/api/notifications/routes/",
        {
            "purpose": "core.webhook_endpoint_disabled",
            "channel": "email",
            "target": {"addresses": ["ops@example.com"]},
        },
        format="json",
    )
    assert ok.status_code == 201
    test = admin.post(f"/api/notifications/routes/{ok.json()['id']}/test/")
    assert test.status_code == 202 and test.json()["results"][0]["status"] == "sent"
    assert admin.get("/api/notifications/matrix/").status_code == 200
    assert admin.get("/api/notifications/deliveries/").json()
    locked = admin.patch(
        "/api/notifications/matrix/",
        {"changes": [{"purpose": "users.password_reset", "channel": "email", "enabled": False}]},
        format="json",
    )
    assert locked.status_code == 409


def test_preferences_api_resolves_and_refuses_mandatory():
    user = UserFactory()
    client = client_for(user)
    prefs = client.patch(
        "/api/me/notification-preferences/",
        {
            "changes": [
                {"purpose": "core.webhook_endpoint_disabled", "channel": "email", "enabled": False}
            ]
        },
        format="json",
    )
    assert prefs.status_code == 200
    mine = {p["purpose"]: p for p in prefs.json()}
    assert mine["core.webhook_endpoint_disabled"]["channels"]["email"] is False
    refused = client.patch(
        "/api/me/notification-preferences/",
        {"changes": [{"purpose": "users.password_reset", "channel": "email", "enabled": False}]},
        format="json",
    )
    assert refused.status_code == 409
