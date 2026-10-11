"""The one error envelope (API_DESIGN.md): {"error": {"code", "message", "details"?}}."""

from rest_framework import status as http
from rest_framework.response import Response


def error_response(code: str, message: str, status: int, details=None) -> Response:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return Response(body, status=status)


def invalid_response(serializer) -> Response:
    return error_response(
        "invalid", "Check the fields.", http.HTTP_400_BAD_REQUEST, details=serializer.errors
    )


def from_exception(exc: Exception, status: int, details=None) -> Response:
    """For service exceptions that carry a `code` and a message (or a docstring)."""
    message = str(exc) or (exc.__doc__ or "").strip() or exc.code
    return error_response(exc.code, message, status, details)
