"""
Structured logging (OBSERVABILITY.md § 2). JSON in production, one record per line, allow-listed
fields only, scrubbed last. Logs go to stdout; the container runtime ships them.
"""

import json
import logging
import traceback
from datetime import UTC, datetime

from .request_id import REQUEST_ID, USER_ID
from .scrub import scrub

# The only fields that leave the process. An `extra=` key outside this set is dropped: a careless
# logger.info("x", extra={"body": request.data}) cannot leak. Modules will register more (§ 2).
CORE_FIELDS = (
    "request_id",
    "client_request_id",
    "user_id",
    "event",
    "duration_ms",
    "status",
    "method",
    "route",
    "fields",
    "audit_verb",
    "audit_actor",
    "audit_target",
    "audit_meta",
)


class ContextFilter(logging.Filter):
    """Stamps request_id and user_id. Attached to every HANDLER, not a logger: logger filters
    miss records propagated from child loggers such as django.request."""

    def filter(self, record):
        if not getattr(record, "request_id", None):
            record.request_id = REQUEST_ID.get()
        if not getattr(record, "user_id", None):
            record.user_id = USER_ID.get()
        return True


class DjangoRequestFilter(logging.Filter):
    """
    One traceback per 500: core.api.exceptions logs it once with exc_info and marks the request;
    django.request's own traceback-less duplicate is dropped. 4xx lines are the access log's job,
    so they are demoted to DEBUG (and dropped below the handler's level).
    """

    def filter(self, record):
        request = getattr(record, "request", None)
        if request is not None and getattr(request, "_error_logged", False):
            return False
        status = getattr(record, "status_code", None)
        if status is not None and 400 <= status < 500:
            record.levelno, record.levelname = logging.DEBUG, "DEBUG"
            return logging.getLogger(record.name).isEnabledFor(logging.DEBUG)
        return True


def _message(record) -> str:
    try:
        return record.getMessage()
    except Exception:  # noqa: BLE001 — a bad %s must never be what crashes a request
        return str(record.msg)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": _message(record),
        }
        out |= {k: getattr(record, k) for k in CORE_FIELDS if getattr(record, k, None) is not None}
        if record.exc_info:
            exc_type, exc, _tb = record.exc_info
            out["exc_type"] = exc_type.__name__ if exc_type else None
            out["exc"] = "".join(traceback.format_exception(*record.exc_info))
        # json.dumps escapes newlines: the structural defence against forged log lines.
        return json.dumps(scrub(out), default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Development only (refused when production-like): readable, still scrubbed."""

    def format(self, record):
        line = f"{record.levelname:<7} [{getattr(record, 'request_id', '-')}] {record.name}: "
        line += str(scrub(_message(record)))
        if record.exc_info:
            line += "\n" + "".join(traceback.format_exception(*record.exc_info))
        return line


def build_logging(*, log_format: str, level: str = "INFO") -> dict:
    formatter = "json" if log_format == "json" else "console"
    handler = {
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stdout",
        "formatter": formatter,
        "filters": ["context"],
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,  # True silently kills every app logger after migrate
        "filters": {
            "context": {"()": ContextFilter},
            "django_request": {"()": DjangoRequestFilter},
        },
        "formatters": {
            "json": {"()": JsonFormatter},
            "console": {"()": ConsoleFormatter},
        },
        "handlers": {
            "stdout": handler,
            "django_request": {**handler, "filters": ["context", "django_request"]},
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            "django.request": {"handlers": ["django_request"], "level": "INFO", "propagate": False},
            # DEBUG here logs every SQL statement with parameters: hashes and tokens included.
            "django.db.backends": {"level": "WARNING"},
            "urllib3": {"level": "WARNING"},
        },
    }
