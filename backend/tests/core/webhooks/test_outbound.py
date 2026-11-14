"""Outbound webhooks (JOBS § 16): signing, emission, fan-out, delivery outcomes, the breaker,
redelivery and the test send. The network is core.http's transport seam: no real HTTP."""

import hashlib
import hmac
import ipaddress
import json
import os
import time
from datetime import timedelta

import httpx
import pytest
from django.db import connection, transaction
from django.utils import timezone

from core import webhooks
from core.models import OutboxMessage, WebhookDelivery, WebhookEndpoint
from core.registry import EventDef, registry
from core.webhooks import service, signing
from core.webhooks.delivery import ladder_delay
from tests.core.webhooks.conftest import PURPOSE, URL, client_module

pytestmark = pytest.mark.django_db

CREATED, DEACTIVATED = "users.user.created", "users.user.deactivated"


def one(user=None):
    from tests.factories import UserFactory

    return user or UserFactory()


def emit_and_drain(run_outbox, event=CREATED):
    with transaction.atomic():
        webhooks.emit(event, one())
    run_outbox()


# --- signing -----------------------------------------------------------------------------------


def test_signature_covers_timestamp_and_body():
    base = signing.sign("secret", 1000, b'{"a":1}')
    expected = hmac.new(b"secret", b'1000.{"a":1}', hashlib.sha256).hexdigest()
    assert base == f"v1={expected}"
    assert signing.sign("secret", 1001, b'{"a":1}') != base  # the timestamp is inside the signature
    assert signing.sign("secret", 1000, b'{"a":2}') != base  # and so is every byte of the body
    assert signing.sign("other", 1000, b'{"a":1}') != base


def test_signature_verifies_with_documented_recipe(network, make_endpoint, run_outbox):
    endpoint, secret = make_endpoint()
    emit_and_drain(run_outbox)
    request = network.seen[0]
    names = signing.header_names()
    raw, ts = request.content, request.headers[names["timestamp"]]
    header = request.headers[names["signature"]]

    # The receiver recipe, exactly as documented in JOBS_AND_INTEGRATIONS.md § 16 "As built (7.6)".
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256)
    assert any(
        hmac.compare_digest(f"v1={expected.hexdigest()}", part.strip())
        for part in header.split(",")
    )
    assert abs(time.time() - int(ts)) <= 300

    assert signing.verify_signature(secret, header, ts, raw)
    assert not signing.verify_signature(secret, header, ts, raw + b" ")  # body changed
    assert not signing.verify_signature("wrong", header, ts, raw)
    assert not signing.verify_signature(secret, header, ts, raw, now=time.time() + 3600)  # replay


def test_headers_payload_and_stored_snapshot(network, make_endpoint, run_outbox):
    endpoint, _ = make_endpoint(custom_headers={"X-Tenant": "acme"})
    emit_and_drain(run_outbox)
    request = network.seen[0]
    names = signing.header_names()
    assert names["signature"] == "X-Test-Product-Signature"  # derived from the slug, no literal
    assert request.headers["user-agent"] == "TestProduct-Webhooks/1"
    assert request.headers["x-tenant"] == "acme"
    row = WebhookDelivery.objects.get()
    assert request.headers[names["delivery"]] == row.delivery_id
    assert request.headers[names["event"]] == CREATED
    body = json.loads(request.content)
    assert set(body) == {"id", "event", "occurred_at", "api_version", "data"}
    assert set(body["data"]) == {"object", "id"} and body["data"]["object"] == "user"
    signature_value = request.headers[names["signature"]]
    stored = json.dumps(list(WebhookDelivery.objects.values()), default=str)
    assert signature_value not in stored  # the signature is never stored


def test_both_secrets_sign_during_rotation_overlap(network, make_endpoint, run_outbox):
    endpoint, old = make_endpoint()
    endpoint, new = service.rotate_secret(actor=None, endpoint=endpoint)
    emit_and_drain(run_outbox)
    names = signing.header_names()
    request = network.seen[0]
    parts = request.headers[names["signature"]].split(",")
    ts = request.headers[names["timestamp"]]
    assert len(parts) == 2
    assert signing.verify_signature(old, request.headers[names["signature"]], ts, request.content)
    assert signing.verify_signature(new, request.headers[names["signature"]], ts, request.content)

    WebhookEndpoint.objects.update(previous_secret_expires_at=timezone.now() - timedelta(minutes=1))
    emit_and_drain(run_outbox)
    assert len(network.seen[1].headers[names["signature"]].split(",")) == 1


# --- emission ----------------------------------------------------------------------------------


def test_emit_writes_one_outbox_row_in_the_callers_transaction(make_endpoint):
    make_endpoint()
    with transaction.atomic():
        webhooks.emit(CREATED, one())
        assert OutboxMessage.objects.filter(topic="webhooks.event").count() == 1
    row = OutboxMessage.objects.get(topic="webhooks.event")
    assert row.payload["event"] == CREATED and row.payload["object_type"] == "user"


@pytest.mark.django_db(transaction=True)
def test_a_rolled_back_transaction_leaves_no_outbox_row():
    user = one()

    class Boom(Exception):
        pass

    with pytest.raises(Boom), transaction.atomic():
        webhooks.emit(CREATED, user)
        raise Boom
    assert OutboxMessage.objects.filter(topic="webhooks.event").count() == 0


def test_emit_of_an_unknown_event_raises_in_tests():
    with transaction.atomic(), pytest.raises(KeyError):
        webhooks.emit("users.user.exploded", one())
    assert OutboxMessage.objects.count() == 0


def test_emit_of_an_unknown_event_logs_and_queues_nothing_outside_tests(settings, caplog):
    settings.APP_ENV = "production"
    with transaction.atomic():
        webhooks.emit("users.user.exploded", one())
    assert OutboxMessage.objects.count() == 0
    assert "unknown_event" in caplog.text


def test_emit_never_raises_into_the_business_action(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr("core.webhooks.emission.enqueue", boom)
    with transaction.atomic():
        webhooks.emit(CREATED, one())  # does not raise
        assert connection.in_atomic_block  # and the caller's transaction is still usable


def test_an_internal_event_is_never_queued(monkeypatch):
    from core.registry import Registry

    reg = Registry()
    reg.events.register(EventDef("core.thing.happened", "Internal.", "thing", external=False))
    monkeypatch.setattr("core.webhooks.emission.registry", reg)
    with transaction.atomic():
        webhooks.emit("core.thing.happened", one())
    assert OutboxMessage.objects.count() == 0


def test_fan_out_uses_the_subscription_table(network, make_endpoint, run_outbox):
    created, _ = make_endpoint(events=[CREATED])
    deactivated, _ = make_endpoint(events=[DEACTIVATED], url="https://other.example.com/in")
    emit_and_drain(run_outbox, CREATED)
    assert list(WebhookDelivery.objects.values_list("endpoint_id", flat=True)) == [created.pk]
    assert [str(r.url) for r in network.seen] == [URL]


def test_inactive_and_disabled_endpoints_are_skipped_not_queued(network, make_endpoint, run_outbox):
    off, _ = make_endpoint(url="https://a.example.com/in")
    tripped, _ = make_endpoint(url="https://b.example.com/in")
    WebhookEndpoint.objects.filter(pk=off.pk).update(is_active=False)
    WebhookEndpoint.objects.filter(pk=tripped.pk).update(disabled_at=timezone.now())
    emit_and_drain(run_outbox)
    assert WebhookDelivery.objects.count() == 0
    assert not OutboxMessage.objects.filter(topic="webhooks.deliver").exists()
    assert network.seen == []


# --- delivery outcomes -------------------------------------------------------------------------


def only_delivery():
    return WebhookDelivery.objects.select_related("endpoint").get()


def test_2xx_is_delivered_and_resets_the_counter(network, make_endpoint, run_outbox):
    endpoint, _ = make_endpoint()
    WebhookEndpoint.objects.filter(pk=endpoint.pk).update(consecutive_failures=4)
    network.script = [httpx.Response(204)]
    emit_and_drain(run_outbox)
    row = only_delivery()
    assert (row.status, row.response_status, row.attempts) == ("delivered", 204, 1)
    assert row.endpoint.consecutive_failures == 0 and row.endpoint.last_delivery_at


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_4xx_is_permanent(network, make_endpoint, run_outbox, status):
    make_endpoint()
    network.script = [httpx.Response(status, text="no")]
    emit_and_drain(run_outbox)
    row = only_delivery()
    assert (row.status, row.error_code, row.next_attempt_at) == ("failed", f"http_{status}", None)
    assert len(network.seen) == 1  # the receiver will say it again: no retry
    assert OutboxMessage.objects.get(topic="webhooks.deliver").status == "skipped"


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503])
def test_retryable_statuses_retry_with_next_attempt_at(network, make_endpoint, run_outbox, status):
    make_endpoint()
    network.script = [httpx.Response(status)]
    emit_and_drain(run_outbox)
    row = only_delivery()
    assert row.status == "pending" and row.error_code == f"http_{status}"
    assert row.next_attempt_at > timezone.now()
    outbox = OutboxMessage.objects.get(topic="webhooks.deliver")
    assert outbox.status == "retry" and outbox.next_attempt_at > timezone.now()


def test_retry_after_is_honoured(network, make_endpoint, run_outbox):
    make_endpoint()
    network.script = [httpx.Response(429, headers={"Retry-After": "120"})]
    emit_and_drain(run_outbox)
    wait = (only_delivery().next_attempt_at - timezone.now()).total_seconds()
    assert 100 < wait <= 121


def test_the_backoff_ladder_has_jitter_and_a_ceiling():
    assert [round(ladder_delay(n, None, rand=lambda: 0.5)) for n in (1, 2, 3, 4, 5, 9)] == [
        30,
        120,
        600,
        1800,
        7200,
        7200,
    ]
    assert ladder_delay(1, None, rand=lambda: 0.0) == pytest.approx(24)
    assert ladder_delay(1, None, rand=lambda: 1.0) == pytest.approx(36)
    assert ladder_delay(1, 99999) == 7200


def test_timeouts_and_connection_errors_retry(network, make_endpoint, run_outbox):
    make_endpoint()
    network.script = [httpx.ConnectTimeout("slow")]
    emit_and_drain(run_outbox)
    row = only_delivery()
    assert row.status == "pending" and row.next_attempt_at > timezone.now()


def test_attempts_are_bounded_by_the_setting(network, make_endpoint, run_outbox, setting_override):
    setting_override("webhooks.delivery.max_attempts", 1)
    make_endpoint()
    network.script = [httpx.Response(503)]
    emit_and_drain(run_outbox)
    assert only_delivery().status == "failed"


def test_redirect_is_a_failure(network, make_endpoint, run_outbox):
    make_endpoint()
    network.script = [httpx.Response(302, headers={"Location": "https://169.254.169.254/"})]
    emit_and_drain(run_outbox)
    row = only_delivery()
    assert (row.status, row.error_code) == ("failed", "redirect_not_followed")
    assert len(network.seen) == 1  # never followed


def test_410_disables_the_endpoint(network, make_endpoint, run_outbox):
    endpoint, _ = make_endpoint()
    network.script = [httpx.Response(410)]
    emit_and_drain(run_outbox)
    endpoint.refresh_from_db()
    assert only_delivery().status == "failed"
    assert endpoint.disabled_at is not None and endpoint.is_active is True  # the breaker's column


def test_breaker_trips_at_threshold_and_reenable_clears(
    network, make_endpoint, run_outbox, setting_override
):
    setting_override("webhooks.delivery.breaker_threshold", 2)
    endpoint, _ = make_endpoint()
    network.script = [httpx.Response(400)]
    emit_and_drain(run_outbox)
    endpoint.refresh_from_db()
    assert (endpoint.consecutive_failures, endpoint.disabled_at) == (1, None)
    emit_and_drain(run_outbox)
    endpoint.refresh_from_db()
    assert endpoint.consecutive_failures == 2 and endpoint.disabled_at is not None
    service.update_endpoint(actor=None, endpoint=endpoint, is_active=True)
    endpoint.refresh_from_db()
    assert (endpoint.consecutive_failures, endpoint.disabled_at) == (0, None)


def test_retries_are_not_failed_deliveries_for_the_breaker(
    network, make_endpoint, run_outbox, setting_override
):
    setting_override("webhooks.delivery.breaker_threshold", 1)
    endpoint, _ = make_endpoint()
    network.script = [httpx.Response(503)]
    emit_and_drain(run_outbox)  # one failed ATTEMPT, the delivery is still pending
    endpoint.refresh_from_db()
    assert (endpoint.consecutive_failures, endpoint.disabled_at) == (0, None)


def test_response_body_is_cut_at_2000_characters(network, make_endpoint, run_outbox):
    make_endpoint()
    network.script = [httpx.Response(200, text="x" * 5000)]
    emit_and_drain(run_outbox)
    assert len(only_delivery().response_body) == 2000


def test_private_destinations_are_refused_at_send_after_dns_changes(
    production, public_dns, make_endpoint, run_outbox, dialled, monkeypatch
):
    make_endpoint()  # passed the write-time check: it resolved to a public address then
    rebound = lambda host, port: [ipaddress.ip_address("10.0.0.5")]  # noqa: E731 — DNS changed
    purpose = registry.http_purposes.get(PURPOSE)
    monkeypatch.setitem(
        client_module._clients,
        (os.getpid(), PURPOSE),
        client_module.SafeClient(purpose, resolver=rebound),
    )
    emit_and_drain(run_outbox)
    row = only_delivery()
    assert (row.status, row.error_code) == ("failed", "unsafe_destination")
    assert dialled == []  # nothing was dialled


def test_http_is_refused_at_send_in_production(network, make_endpoint, run_outbox, settings):
    endpoint, _ = make_endpoint()
    WebhookEndpoint.objects.filter(pk=endpoint.pk).update(url="http://hooks.example.com/in")
    emit_and_drain(run_outbox)
    assert only_delivery().error_code == "scheme_not_allowed" and network.seen == []


# --- redeliver and send-test -------------------------------------------------------------------


def test_redeliver_keeps_the_delivery_id(network, make_endpoint, run_outbox):
    make_endpoint()
    network.script = [httpx.Response(400), httpx.Response(200)]
    emit_and_drain(run_outbox)
    before = only_delivery()
    assert before.status == "failed"
    after = service.redeliver(actor=None, delivery=before)
    assert (after.pk, after.delivery_id, after.status) == (before.pk, before.delivery_id, "pending")
    run_outbox()
    final = only_delivery()
    assert final.status == "delivered" and final.attempts == 2
    names = signing.header_names()
    assert {r.headers[names["delivery"]] for r in network.seen} == {before.delivery_id}


def test_a_pending_delivery_cannot_be_redelivered(network, make_endpoint, run_outbox):
    make_endpoint()
    network.script = [httpx.Response(503)]
    emit_and_drain(run_outbox)
    with pytest.raises(service.NotRedeliverable):
        service.redeliver(actor=None, delivery=only_delivery())


def test_send_test_bypasses_subscriptions_and_is_logged_as_a_test(
    network, make_endpoint, run_outbox
):
    endpoint, _ = make_endpoint(events=[DEACTIVATED])
    service.send_test(actor=None, endpoint=endpoint)
    run_outbox()
    row = only_delivery()
    assert (row.is_test, row.status, row.event) == (True, "delivered", "core.webhook.ping")
    assert network.seen[0].headers[signing.header_names()["event"]] == "core.webhook.ping"


def test_a_failing_test_send_does_not_count_against_the_breaker(network, make_endpoint, run_outbox):
    endpoint, _ = make_endpoint()
    network.script = [httpx.Response(400)]
    service.send_test(actor=None, endpoint=endpoint)
    run_outbox()
    endpoint.refresh_from_db()
    assert only_delivery().status == "failed" and endpoint.consecutive_failures == 0
