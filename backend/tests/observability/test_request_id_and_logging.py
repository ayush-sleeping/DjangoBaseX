"""
BUILD_ORDER 6.1 (OBSERVABILITY.md § 1–2). Done-when: a 500 body and its log line carry the same
request id; a canary password sent through a normal and a failing-validation request appears in no
log line.
"""

import io
import json
import logging
import uuid

import pytest
from django.http import StreamingHttpResponse
from django.test import Client, override_settings
from django.urls import path
from rest_framework.response import Response

from core.api.views import BaseAPIView
from core.observability.logging import ContextFilter, JsonFormatter, build_logging
from tests.factories import DEFAULT_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


class BoomView(BaseAPIView):
    public = True
    authentication_classes: list = []

    def get(self, request):
        raise RuntimeError("kaboom")


class LeakyView(BaseAPIView):
    """Positive control: deliberately logs its body. The canary detector must find it."""

    public = True
    authentication_classes: list = []

    def post(self, request):
        logging.getLogger("tests.leaky").warning("body was %s", request.data)
        return Response({})


def streaming_view(request):
    def body():
        # Runs AFTER the middleware has returned: exactly where a too-early reset shows up.
        logging.getLogger("tests.stream").warning("streaming a chunk")
        yield b"chunk"

    return StreamingHttpResponse(body())


urlpatterns = [
    path("stream/", streaming_view, name="stream"),
    path("api/boom/", BoomView.as_view(), name="boom"),
    path("api/leaky/", LeakyView.as_view(), name="leaky"),
]


@pytest.fixture
def json_logs():
    """Capture what the real handlers would emit: the JSON formatter and context filter, at root."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield stream
    root.removeHandler(handler)
    root.setLevel(previous)


def records(stream) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


# --- The request id -----------------------------------------------------------------------------


def test_every_response_carries_a_generated_request_id(client):
    response = client.get("/api/health/")
    rid = response["X-Request-ID"]
    assert len(rid) == 32 and int(rid, 16) >= 0


@override_settings(ROOT_URLCONF=__name__)
def test_500_body_header_and_log_line_carry_the_same_id(json_logs):
    response = Client(raise_request_exception=False).get("/api/boom/")
    assert response.status_code == 500
    rid = response["X-Request-ID"]
    assert response.json()["error"]["request_id"] == rid != "-"

    with_traceback = [r for r in records(json_logs) if "exc" in r]
    assert len(with_traceback) == 1  # one traceback per 500, not two
    assert with_traceback[0]["request_id"] == rid
    assert with_traceback[0]["exc_type"] == "RuntimeError"


@override_settings(ROOT_URLCONF=__name__)
def test_a_log_emitted_while_streaming_carries_the_id(json_logs):
    # OBSERVABILITY § 1: the id must not be reset when the middleware returns, only when the
    # response is fully sent. This fails against the reset-in-finally implementation.
    response = Client().get("/stream/")
    b"".join(response.streaming_content)
    streamed = [r for r in records(json_logs) if r["logger"] == "tests.stream"]
    assert streamed and streamed[0]["request_id"] == response["X-Request-ID"] != "-"


@pytest.mark.parametrize("bad", ["abc\ndef", "x" * 65, "has space", "semi;colon"])
def test_a_malformed_inbound_id_is_discarded(client, bad):
    assert client.get("/api/health/", HTTP_X_REQUEST_ID=bad)["X-Request-ID"] != bad


def test_an_inbound_id_is_ignored_without_a_trusted_proxy(client, settings):
    settings.TRUSTED_PROXY_COUNT = 0
    assert client.get("/api/health/", HTTP_X_REQUEST_ID="edge-123")["X-Request-ID"] != "edge-123"


def test_an_inbound_id_is_used_behind_a_trusted_proxy(client, settings):
    settings.TRUSTED_PROXY_COUNT = 1
    assert client.get("/api/health/", HTTP_X_REQUEST_ID="edge-123")["X-Request-ID"] == "edge-123"


def test_error_envelopes_and_drf_errors_carry_the_request_id(client):
    response = client.get("/api/auth/me/")  # 401 from DRF itself
    assert response.json()["request_id"] == response["X-Request-ID"]


# --- Logs: what may never appear ----------------------------------------------------------------


def canary() -> str:
    # Lowercase hex: below the scrubber's high-entropy floor, so a canary that vanishes from the
    # logs vanished because a KEY rule caught it, not because it merely looked random.
    return f"canary-{uuid.uuid4().hex}"


def test_a_canary_password_appears_in_no_log_line(json_logs):
    secret = canary()
    user = UserFactory()
    client = Client()
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": secret},
        content_type="application/json",
    )  # failing login
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD, "note": secret},
        content_type="application/json",
    )  # successful login with the canary riding along
    client.post(
        "/api/auth/password/reset/",
        {"token": "x", "password": secret, "extra": [secret]},
        content_type="application/json",
    )  # a reset failure
    client.post("/api/auth/login/", {"email": secret}, content_type="application/json")  # 400
    assert records(json_logs), "nothing was captured: the detector would pass vacuously"
    assert secret not in json_logs.getvalue()


@override_settings(ROOT_URLCONF=__name__)
def test_the_canary_detector_can_find_a_leak(json_logs):
    # Positive control: a view that logs its body. The value reaches the formatter; this proves
    # the capture works, so the test above passes for the right reason.
    secret = canary()
    Client().post("/api/leaky/", {"note": secret}, content_type="application/json")
    assert secret in json_logs.getvalue()


def test_validation_failures_log_codes_not_values(json_logs):
    Client().post(
        "/api/auth/login/", {"email": ["not", "a", "string"]}, content_type="application/json"
    )
    logged = [r for r in records(json_logs) if r.get("logger") == "core.validation"]
    assert logged and logged[0]["fields"]
    assert "not" not in json.dumps(logged[0]["fields"])


def test_unregistered_extra_fields_are_dropped(json_logs):
    logging.getLogger("tests.extra").warning("hello", extra={"body": "SHOULD-NOT-APPEAR"})
    assert "SHOULD-NOT-APPEAR" not in json_logs.getvalue()


def test_json_lines_cannot_be_forged_with_a_newline(json_logs):
    logging.getLogger("tests.forge").warning('line one\n{"level": "ERROR"}')
    assert len(json_logs.getvalue().strip().splitlines()) == 1


def test_every_handler_carries_the_context_filter():
    config = build_logging(log_format="json")
    for name, handler in config["handlers"].items():
        assert "context" in handler["filters"], name
    assert config["disable_existing_loggers"] is False
