"""
The DRF exception handler (OBSERVABILITY.md § 1–2, API_PLATFORM.md error envelope).

- An unhandled exception becomes ONE logged traceback (logger core.errors, with exc_info) and a
  500 envelope carrying the request id, so a user's "reference" leads to that exact line.
- A ValidationError is logged at INFO as field -> error CODES, never messages or values: DRF's
  messages echo input ('"x" is not a valid choice.').
- Every error body gets the request id.
"""

import logging
import math

from rest_framework import status
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.api.error_codes import ApiError, envelope
from core.observability.request_id import current
from core.providers.errors import ProviderError

errors = logging.getLogger("core.errors")
providers = logging.getLogger("core.providers")


def _provider_error(exc: ProviderError) -> Response:
    """JOBS_AND_INTEGRATIONS.md § 20: OUR status for a partner's failure. An upstream 401/403 is
    our 502, never our 401: the frontend would sign the user out over a partner's expired key.
    The detail is the adapter's chosen, scrubbed field; never the upstream body."""
    providers.warning(
        "core.provider.error",
        extra={
            "provider": exc.provider,
            "code": exc.code,
            "upstream_status": exc.upstream_status,
            "status": exc.status,
        },
    )
    error = {"code": exc.code, "message": exc.message, "request_id": current()}
    details = {
        key: value
        for key, value in (("provider", exc.provider), ("detail", exc.safe_detail))
        if value
    }
    if details:
        error["details"] = details
    response = Response({"error": error}, status=exc.status)
    if exc.retry_after is not None:
        response["Retry-After"] = str(max(0, round(exc.retry_after)))
    return response


validation = logging.getLogger("core.validation")


def _throttled(exc: Throttled, context) -> Response:
    """The 429 contract (API_PLATFORM.md § 5): Retry-After and retry_after_seconds carry the same
    number, never below 1 (DRF omits the header at 0, which invites an immediate retry)."""
    wait = max(1, math.ceil(exc.wait or 0))
    view = context.get("view")
    scope = getattr(view, "throttle_scope", None)
    body = envelope(
        "throttled",
        f"Too many requests. Try again in {wait} seconds.",
        {"scope": scope} if scope else None,
        retry_after_seconds=wait,
    )
    body["error"]["request_id"] = current()
    response = Response(body, status=status.HTTP_429_TOO_MANY_REQUESTS)
    response["Retry-After"] = str(wait)
    return response


def handler(exc, context):
    request = context.get("request")
    if isinstance(exc, ProviderError):
        return _provider_error(exc)
    if isinstance(exc, ApiError):
        body = envelope(exc.error_code, str(exc.detail), exc.details)
        body["error"]["request_id"] = current()
        return Response(body, status=exc.status_code)
    if isinstance(exc, Throttled):
        return _throttled(exc, context)
    response = exception_handler(exc, context)
    if response is None:
        errors.error("unhandled exception", exc_info=exc)
        if request is not None:
            request._request._error_logged = True  # django.request's duplicate is dropped
        return Response(
            {
                "error": {
                    "code": "server_error",
                    "message": "Something went wrong. Quote this reference if you report it.",
                    "request_id": current(),
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if isinstance(exc, ValidationError):
        validation.info("validation failed", extra={"fields": exc.get_codes()})
    if isinstance(response.data, dict):
        if isinstance(response.data.get("error"), dict):
            response.data["error"]["request_id"] = current()
        else:
            response.data["request_id"] = current()
    return response
