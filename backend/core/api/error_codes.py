"""
The error-code catalogue (API_PLATFORM.md § 4): every code the API raises through ApiError is
declared here once, with its status and default message. A code is a contract: renaming one is a
breaking change. Module codes are prefixed with the module name (`billing.insufficient_funds`).
"""

from dataclasses import dataclass

from rest_framework import status
from rest_framework.exceptions import APIException


@dataclass(frozen=True)
class ErrorCode:
    code: str
    status: int
    message: str
    retryable: bool = False


ERROR_CODES: dict[str, ErrorCode] = {}


def register(entry: ErrorCode) -> ErrorCode:
    if entry.code in ERROR_CODES:
        raise ValueError(f"error code {entry.code!r} is already registered")
    ERROR_CODES[entry.code] = entry
    return entry


for _entry in (
    ErrorCode("validation_error", 400, "Check the fields."),
    ErrorCode("unknown_parameter", 400, "An unknown query parameter was sent."),
    ErrorCode("not_authenticated", 401, "Sign in to continue."),
    ErrorCode("invalid_token", 401, "Invalid or expired token."),
    ErrorCode("permission_denied", 403, "You do not have permission to do this."),
    ErrorCode("credential_not_accepted", 403, "This endpoint does not accept this kind of caller."),
    ErrorCode("not_found", 404, "Not found."),
    ErrorCode("unsupported_file_type", 400, "This file type is not accepted."),
    ErrorCode("throttled", 429, "Too many requests.", retryable=True),
    ErrorCode("server_error", 500, "Something went wrong."),
):
    register(_entry)


class ApiError(APIException):
    """Raise with a registered code; the handler renders the envelope, status from the catalogue."""

    def __init__(self, code: str, message: str | None = None, details=None):
        entry = ERROR_CODES[code]  # an unregistered code is a programming error: KeyError
        self.status_code = entry.status
        self.error_code = code
        self.details = details
        super().__init__(detail=message or entry.message, code=code)


def envelope(code: str, message: str, details=None, **extra) -> dict:
    body = {"code": code, "message": message, **extra}
    if details is not None:
        body["details"] = details
    return {"error": body}


__all__ = ["ERROR_CODES", "ApiError", "ErrorCode", "envelope", "register", "status"]
