"""Inbound webhooks (JOBS_AND_INTEGRATIONS.md § 17): verify first over the raw bytes, fail closed,
then dedupe in the database. A fake verifier stands in: no real provider ships in core."""

import hashlib
import hmac
import json
import time

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import InboundWebhookEvent
from core.registry import Registry
from core.webhooks import inbound
from core.webhooks.inbound import InvalidSignature, Verified
from tests.core.webhooks import fake_handlers

pytestmark = pytest.mark.django_db

SECRET = "s3cret-for-acme"


class FakeVerifier:
    provider = "fakehook"
    durable_dedupe = True
    secrets = {"acme": SECRET, "nosecret": ""}

    def secret_for(self, ingress_token):
        return self.secrets.get(ingress_token)

    def verify(self, raw_body, headers, secret):
        timestamp = headers.get("X-Fake-Timestamp", "")
        expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256)
        if not hmac.compare_digest(expected.hexdigest(), headers.get("X-Fake-Signature", "")):
            raise InvalidSignature("bad signature")
        inbound.check_timestamp(timestamp)
        data = json.loads(raw_body)  # parsed only after the signature is proven
        return Verified(
            delivery_id=data["id"], event_type=data["type"], payload={"order": data["order"]}
        )

    def dedupe_key(self, verified):
        return f"fakehook:{verified.delivery_id}"


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch):
    reg = Registry()
    reg.inbound_webhooks.register(
        FakeVerifier(), handler="tests.core.webhooks.fake_handlers.handle"
    )
    monkeypatch.setattr(inbound, "registry", reg)
    fake_handlers.CALLS.clear()


def signed(raw: bytes, *, secret=SECRET, timestamp=None):
    ts = str(int(timestamp if timestamp is not None else time.time()))
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return {"HTTP_X_FAKE_TIMESTAMP": ts, "HTTP_X_FAKE_SIGNATURE": mac}


def event(delivery_id="evt_1", **extra):
    return json.dumps(
        {"id": delivery_id, "type": "order.paid", "order": "o_9", "card": "4242", **extra}
    ).encode()


def post(raw, headers, token="acme", provider="fakehook", client=None):
    url = reverse("core:inbound-webhook", args=[provider, token])
    return (client or APIClient()).post(url, data=raw, content_type="application/json", **headers)


def test_a_valid_delivery_is_stored_minimised_and_acknowledged():
    raw = event()
    response = post(raw, signed(raw))
    assert response.status_code == 200
    row = InboundWebhookEvent.objects.get()
    assert (row.provider, row.delivery_id, row.event_type, row.status) == (
        "fakehook",
        "evt_1",
        "order.paid",
        "received",
    )
    assert row.payload == {"order": "o_9"}  # the allowlist, never the whole body
    assert "4242" not in json.dumps(row.payload)


def test_missing_secret_rejects():
    raw = event()
    for token in ("nosecret", "unknown-token"):
        response = post(raw, signed(raw, secret=""), token=token)
        assert (
            response.status_code == 400 and response.json()["error"]["code"] == "invalid_signature"
        )
    assert InboundWebhookEvent.objects.count() == 0


def test_a_bad_signature_is_400_and_inserts_nothing():
    raw = event()
    response = post(raw, signed(raw, secret="wrong"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_signature"
    assert InboundWebhookEvent.objects.count() == 0


def test_no_signature_at_all_is_rejected():
    assert post(event(), {}).status_code == 400
    assert InboundWebhookEvent.objects.count() == 0


def test_the_signature_is_over_the_raw_bytes_not_reparsed_json():
    spaced = b'{ "id":"evt_1",  "type":"order.paid", "order":"o_9" }'
    assert post(spaced, signed(spaced)).status_code == 200
    reserialised = json.dumps(json.loads(spaced)).encode()
    assert reserialised != spaced
    headers = signed(reserialised)
    assert post(spaced, headers).status_code == 400  # signed over different bytes


def test_a_replayed_old_timestamp_is_rejected():
    raw = event()
    response = post(raw, signed(raw, timestamp=time.time() - 3600))
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_signature"
    assert InboundWebhookEvent.objects.count() == 0


def test_a_timestamp_inside_the_tolerance_is_accepted():
    raw = event()
    assert post(raw, signed(raw, timestamp=time.time() - 200)).status_code == 200


def test_the_tolerance_is_a_setting(setting_override):
    setting_override("webhooks.inbound.timestamp_tolerance_seconds", 30)
    raw = event()
    assert post(raw, signed(raw, timestamp=time.time() - 200)).status_code == 400


def test_a_duplicate_valid_delivery_is_stored_once_and_still_200():
    raw = event()
    first, second = post(raw, signed(raw)), post(raw, signed(raw))
    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json()["status"] == "duplicate"
    assert InboundWebhookEvent.objects.count() == 1


def test_an_unsigned_request_with_a_real_delivery_id_cannot_pre_claim_it():
    raw = event("evt_77")
    assert post(raw, signed(raw, secret="attacker")).status_code == 400  # verify happens first
    assert InboundWebhookEvent.objects.count() == 0
    assert post(raw, signed(raw)).status_code == 200  # the real event is not suppressed
    assert InboundWebhookEvent.objects.get().delivery_id == "evt_77"


def test_an_unknown_provider_is_404():
    raw = event()
    assert post(raw, signed(raw), provider="nobody").status_code == 404


def test_csrf_checks_do_not_apply_to_a_provider_callback():
    raw = event()
    assert post(raw, signed(raw), client=APIClient(enforce_csrf_checks=True)).status_code == 200


def test_the_drain_processes_a_received_event(run_outbox):
    raw = event()
    post(raw, signed(raw))
    run_outbox()
    row = InboundWebhookEvent.objects.get()
    assert row.status == "processed" and row.processed_at and fake_handlers.CALLS == [row.pk]


def test_a_failing_handler_marks_the_event_failed_and_never_asks_the_provider_again(
    run_outbox, monkeypatch
):
    reg = Registry()
    reg.inbound_webhooks.register(
        FakeVerifier(), handler="tests.core.webhooks.fake_handlers.explode"
    )
    monkeypatch.setattr(inbound, "registry", reg)
    raw = event()
    assert post(raw, signed(raw)).status_code == 200
    run_outbox()
    row = InboundWebhookEvent.objects.get()
    assert (row.status, row.error_code) == ("failed", "RuntimeError")


def test_a_verifier_must_declare_its_dedupe_durability():
    class Silent(FakeVerifier):
        provider = "silent"
        durable_dedupe = None

    with pytest.raises(Exception, match="durable_dedupe"):
        Registry().inbound_webhooks.register(Silent())
