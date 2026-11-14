"""Standard library only: config/settings.py and core/config_audit.py import this mid-load."""

GUARDED_BACKEND = "core.mail.backends.GuardedEmailBackend"
# Backends that never deliver: console, file, in-memory, dummy.
LOG_ONLY_BACKENDS = ("console", "filebased", "locmem", "dummy")


def is_log_only(backend: str) -> bool:
    return any(name in str(backend or "").lower() for name in LOG_ONLY_BACKENDS)
