"""
One request id per request (OBSERVABILITY.md § 1).

Two failures this is shaped against, both shipped elsewhere: resetting the id in a `finally` (the
500 body and the access log then read "-"), and trusting a caller's id (a newline in it forges a log
line, and a client can collide its requests with someone else's).
"""

import re
import uuid
from contextvars import ContextVar

from django.conf import settings
from django.core.signals import request_finished
from django.dispatch import receiver

REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
USER_ID: ContextVar[str | None] = ContextVar("user_id", default=None)

HEADER = "X-Request-ID"
_META_KEY = "HTTP_X_REQUEST_ID"
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # a constant: loosening it is a security change


def _valid(value: str | None) -> str | None:
    return value if value and _VALID.match(value) else None


def resolve_request_id(request) -> tuple[str, str | None]:
    """
    (request_id, client_request_id). An inbound id becomes THE id only behind a trusted proxy,
    which sets it itself; otherwise a valid caller value is kept aside as client_request_id.
    """
    inbound = _valid(request.META.get(_META_KEY))
    if inbound and settings.TRUSTED_PROXY_COUNT > 0:
        return inbound, None
    return uuid.uuid4().hex, inbound


class RequestIdMiddleware:
    """MIDDLEWARE[0]: before CORS, so even a preflight answer carries an id."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid, client_rid = resolve_request_id(request)
        REQUEST_ID.set(rid)  # the first act, and deliberately NOT reset on the way out
        request.request_id, request.client_request_id = rid, client_rid
        response = self.get_response(request)
        response[HEADER] = rid
        return response


@receiver(request_finished, dispatch_uid="core.observability.clear_request_context")
def _clear_context(**kwargs) -> None:
    # request_finished fires from response.close(), after a streamed body has been sent.
    REQUEST_ID.set("-")
    USER_ID.set(None)


def current() -> str:
    return REQUEST_ID.get()
