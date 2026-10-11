"""
The DRF exception handler (OBSERVABILITY.md § 1–2, API_PLATFORM.md error envelope).

- An unhandled exception becomes ONE logged traceback (logger core.errors, with exc_info) and a
  500 envelope carrying the request id, so a user's "reference" leads to that exact line.
- A ValidationError is logged at INFO as field -> error CODES, never messages or values: DRF's
  messages echo input ('"x" is not a valid choice.').
- Every error body gets the request id.
"""

import logging

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.observability.request_id import current

errors = logging.getLogger("core.errors")
validation = logging.getLogger("core.validation")


def handler(exc, context):
    request = context.get("request")
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
