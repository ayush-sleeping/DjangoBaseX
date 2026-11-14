"""Provider errors → our responses (JOBS_AND_INTEGRATIONS.md § 20): one table, every row."""

import httpx
import pytest

from core.api.exceptions import handler
from core.providers.errors import (
    OutboundBlocked,
    ProviderAuthError,
    ProviderClientError,
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderUnavailable,
    UnsafeDestination,
    from_exception,
    parse_retry_after,
    raise_for_upstream,
)


def upstream(status, **headers):
    return httpx.Response(
        status, headers=headers, request=httpx.Request("GET", "https://p.example")
    )


@pytest.mark.parametrize(
    ("status", "raised", "ours", "code"),
    [
        (401, ProviderAuthError, 502, "upstream_auth_failed"),
        (403, ProviderAuthError, 502, "upstream_auth_failed"),
        (429, ProviderRateLimited, 503, "upstream_rate_limited"),
        (500, ProviderUnavailable, 502, "upstream_unavailable"),
        (503, ProviderUnavailable, 502, "upstream_unavailable"),
        (504, ProviderUnavailable, 504, "upstream_timeout"),
        (408, ProviderUnavailable, 504, "upstream_timeout"),
        (400, ProviderClientError, 400, "upstream_rejected"),
        (404, ProviderClientError, 404, "upstream_rejected"),
        (409, ProviderClientError, 409, "upstream_rejected"),
        (422, ProviderClientError, 422, "upstream_rejected"),
        (410, ProviderClientError, 400, "upstream_rejected"),
    ],
)
def test_every_upstream_status_maps_once(status, raised, ours, code):
    with pytest.raises(raised) as caught:
        raise_for_upstream(upstream(status), "billing")
    response = handler(caught.value, {})
    assert (response.status_code, response.data["error"]["code"]) == (ours, code)
    assert response.data["error"]["details"]["provider"] == "billing"


def test_upstream_401_never_becomes_401():
    for status in (401, 403):
        with pytest.raises(ProviderError) as caught:
            raise_for_upstream(upstream(status), "billing")
        assert handler(caught.value, {}).status_code not in (401, 403)


def test_a_2xx_raises_nothing():
    assert raise_for_upstream(upstream(200), "billing") is None


@pytest.mark.parametrize(
    ("exc", "ours", "code"),
    [
        (ProviderResponseError("billing"), 502, "upstream_bad_response"),
        (ProviderNotConfigured("sms"), 503, "integration_not_configured"),
        (OutboundBlocked("billing"), 423, "blocked_locally"),
        (UnsafeDestination("non_public_address:10.0.0.1", host="x"), 400, "unsafe_destination"),
    ],
)
def test_the_other_rows(exc, ours, code):
    response = handler(exc, {})
    assert (response.status_code, response.data["error"]["code"]) == (ours, code)
    assert (
        response.data["error"]["request_id"] is not None or "request_id" in response.data["error"]
    )


def test_rate_limited_carries_retry_after():
    with pytest.raises(ProviderRateLimited) as caught:
        raise_for_upstream(upstream(429, **{"Retry-After": "17"}), "billing")
    assert handler(caught.value, {})["Retry-After"] == "17"


def test_the_detail_is_the_adapters_field_scrubbed_and_cut():
    with pytest.raises(ProviderClientError) as caught:
        raise_for_upstream(
            upstream(400), "billing", detail="bad field; password=hunter2 " + "x" * 500
        )
    detail = handler(caught.value, {}).data["error"]["details"]["detail"]
    assert "hunter2" not in detail and len(detail) <= 200


def test_the_upstream_body_is_never_passed_through():
    response = httpx.Response(
        400, text="secret internals", request=httpx.Request("GET", "https://p")
    )
    with pytest.raises(ProviderClientError) as caught:
        raise_for_upstream(response, "billing")
    assert "secret internals" not in str(handler(caught.value, {}).data)


def test_transient_errors_feed_the_retry_policy():
    from core.jobs.retry import DEFAULT_RETRY

    assert DEFAULT_RETRY.is_transient(ProviderUnavailable("x"))
    assert DEFAULT_RETRY.is_transient(ProviderRateLimited("x"))
    assert not DEFAULT_RETRY.is_transient(ProviderAuthError("x"))
    assert not DEFAULT_RETRY.is_transient(ProviderClientError("x", upstream_status=400))


@pytest.mark.parametrize(
    ("exc", "expected", "status"),
    [
        (httpx.ReadTimeout("slow"), ProviderUnavailable, 504),
        (httpx.ConnectError("refused"), ProviderUnavailable, 502),
        (ValueError("bad json"), ProviderResponseError, 502),
    ],
)
def test_library_exceptions_are_translated_at_the_boundary(exc, expected, status):
    translated = from_exception(exc, "billing")
    assert isinstance(translated, expected) and translated.status == status


def test_retry_after_parses_seconds_and_dates():
    from datetime import UTC, datetime

    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    assert parse_retry_after("30") == 30
    assert parse_retry_after("Fri, 06 Nov 2026 12:01:00 GMT", now=now) == 60
    assert parse_retry_after("garbage") is None and parse_retry_after(None) is None


def test_the_outbox_handler_import_path_still_works():
    from core.outbox import ProviderNotConfigured as from_outbox

    assert from_outbox is ProviderNotConfigured
