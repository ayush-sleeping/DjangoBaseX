"""
Boot refusal at settings import (CONFIGURATION.md § 5; closes TECH_DEBT DB-7).

`enforce(globals())` is the last line of the settings module. In a production-like environment
(core.env) it raises ImproperlyConfigured listing EVERY problem at once, each with its fix; anywhere
else it logs every finding as a warning and lets the process start. System checks are not enough:
they never run when gunicorn, uvicorn or a worker starts. Settings import is the one thing every
process does before serving anything.

Rules:
  - Imports nothing that needs the app registry: this runs before django.setup().
  - Findings name KEYS, never values (AGENTS.md rule 6). A test pushes a canary through every rule.
  - Each rule is independent; each has a test violating only it.
  - The rules and floors are code constants: making them env values would let the environment
    being audited weaken its own audit.

`python -m core.config_audit` prints the report for DJANGO_SETTINGS_MODULE without raising.
"""

import importlib
import ipaddress
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from django.conf import global_settings
from django.core.exceptions import ImproperlyConfigured

from core.env import is_production_like

logger = logging.getLogger("core.config_audit")

# --- Secret strength (§ 5) ----------------------------------------------------------------------

# Substring match: distinctive enough that an honest random key never contains them.
DISTINCTIVE = (
    "changeme",
    "change-me",
    "change_me",
    "replace",
    "placeholder",
    "your-",
    "example",
    "insecure",
    "dummy",
    "notsecret",
    "xxxxxxxx",
    "secret-key",
    "django-insecure",
)
# Exact match only: a substring match on "test" would reject honest random keys.
GENERIC = frozenset({"secret", "password", "test", "dev", "key", "admin", "default", "none"})

SECRET_KEY_MIN_LENGTH = 50  # DEPLOYMENT.md § 1
JWT_KEY_MIN_LENGTH = 32  # HS256: at least the hash's 256 bits of key material, as text
DISTINCT_CHARACTERS = 12


def weak_reason(value: str | None, *, min_length: int) -> str | None:
    """Why this secret is unacceptable, or None. Never returns or logs the value."""
    v = (value or "").strip()
    if not v:
        return "is empty"
    if v.lower() in GENERIC:
        return "is a generic placeholder word"
    if any(p in v.lower() for p in DISTINCTIVE):
        return "contains a known placeholder"
    if len(v) < min_length:
        return f"is shorter than {min_length} characters"
    if len(set(v)) < DISTINCT_CHARACTERS:
        return f"has fewer than {DISTINCT_CHARACTERS} distinct characters"
    return None


# --- Findings -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    code: str  # "cfg.E002"
    key: str  # the setting it is about; never its value
    message: str
    fix: str

    @property
    def is_problem(self) -> bool:
        return self.code.startswith("cfg.E")


_MISSING = object()


def _get(ns: Mapping[str, Any], key: str, default: Any = _MISSING) -> Any:
    """The value the running process would see: the namespace, else Django's own default."""
    if key in ns:
        return ns[key]
    if default is not _MISSING:
        return default
    return getattr(global_settings, key, None)


_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def _is_loopback_host(host: str | None) -> bool:
    host = (host or "").strip().lower().strip("[]")
    if not host:
        return False
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    try:
        return list(value)
    except TypeError:
        return [value]


# --- The rules ----------------------------------------------------------------------------------
# Each takes the namespace and yields Findings. Order here is the order of the report.


def _debug(ns):
    if _get(ns, "DEBUG"):
        yield Finding(
            "cfg.E002",
            "DEBUG",
            "DEBUG is on: tracebacks, settings and SQL reach whoever triggers an error.",
            "Set DEBUG=False.",
        )


def _secrets(ns):
    named = [
        ("SECRET_KEY", _get(ns, "SECRET_KEY", ""), SECRET_KEY_MIN_LENGTH),
        ("JWT_SIGNING_KEY", _get(ns, "JWT_SIGNING_KEY", ""), JWT_KEY_MIN_LENGTH),
    ]
    for index, value in enumerate(_as_list(_get(ns, "JWT_SIGNING_KEY_FALLBACKS", []))):
        named.append((f"JWT_SIGNING_KEY_FALLBACKS[{index}]", value, JWT_KEY_MIN_LENGTH))
    for key, value, min_length in named:
        reason = weak_reason(value if isinstance(value, str) else None, min_length=min_length)
        if reason:
            yield Finding(
                "cfg.E003",
                key,
                f"{key} {reason}.",
                f"Generate a random value of at least {min_length} characters for {key}.",
            )


def _shared_secrets(ns):
    named = [
        ("SECRET_KEY", _get(ns, "SECRET_KEY", "")),
        ("JWT_SIGNING_KEY", _get(ns, "JWT_SIGNING_KEY", "")),
        ("MFA_ENCRYPTION_KEY", _get(ns, "MFA_ENCRYPTION_KEY", "")),
    ]
    for index, value in enumerate(_as_list(_get(ns, "JWT_SIGNING_KEY_FALLBACKS", []))):
        named.append((f"JWT_SIGNING_KEY_FALLBACKS[{index}]", value))
    present = [(k, v.strip()) for k, v in named if isinstance(v, str) and v.strip()]
    for i, (key_a, value_a) in enumerate(present):
        for key_b, value_b in present[i + 1 :]:
            if value_a == value_b:
                yield Finding(
                    "cfg.E004",
                    f"{key_a}, {key_b}",
                    f"{key_a} and {key_b} are the same value: one leak breaks both jobs, and "
                    "rotating one bricks the other.",
                    f"Give {key_b} its own randomly generated value.",
                )


def _allowed_hosts(ns):
    hosts = _as_list(_get(ns, "ALLOWED_HOSTS", []))
    if not hosts or "*" in hosts:
        yield Finding(
            "cfg.E005",
            "ALLOWED_HOSTS",
            "ALLOWED_HOSTS is empty or contains '*': any Host header is accepted, which poisons "
            "absolute links such as password-reset URLs.",
            "List the exact hostnames this deployment serves.",
        )


def _bad_origin(origin: str) -> str | None:
    origin = origin.strip()
    if origin == "*" or "*" in origin:
        return "a wildcard"
    split = urlsplit(origin)
    if split.scheme.lower() == "http":
        return "plain http://"
    if _is_loopback_host(split.hostname):
        return "a loopback host"
    return None


def _origins(ns):
    if not _get(ns, "CORS_ALLOW_CREDENTIALS", False):
        return
    if _get(ns, "CORS_ALLOW_ALL_ORIGINS", False):
        yield Finding(
            "cfg.E006",
            "CORS_ALLOW_ALL_ORIGINS",
            "CORS_ALLOW_ALL_ORIGINS is on while credentials are allowed: any site can make "
            "authenticated requests.",
            "Turn it off and list origins in CORS_ALLOWED_ORIGINS.",
        )
    for key in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"):
        for index, origin in enumerate(_as_list(_get(ns, key, []))):
            reason = _bad_origin(str(origin))
            if reason:
                yield Finding(
                    "cfg.E006",
                    f"{key}[{index}]",
                    f"{key}[{index}] is {reason} while CORS_ALLOW_CREDENTIALS is on.",
                    f"Use the exact https:// origin of the frontend in {key}.",
                )


def _cookies(ns):
    if not _get(ns, "AUTH_COOKIE_SECURE", False):
        yield Finding(
            "cfg.E007",
            "AUTH_COOKIE_SECURE",
            "AUTH_COOKIE_SECURE is off: session cookies would travel over plain HTTP.",
            "Set AUTH_COOKIE_SECURE=True (serve the site over HTTPS).",
        )


_LOG_ONLY_EMAIL = ("console", "filebased", "locmem", "dummy")


def _email(ns):
    backend = str(_get(ns, "EMAIL_BACKEND") or "").lower()
    if any(name in backend for name in _LOG_ONLY_EMAIL):
        yield Finding(
            "cfg.E008",
            "EMAIL_BACKEND",
            "EMAIL_BACKEND does not send mail: reset and invitation links would be written to "
            "logs or lost.",
            "Use the SMTP backend (or a provider backend) and set EMAIL_HOST.",
        )
    elif "smtp" in backend and not str(_get(ns, "EMAIL_HOST") or "").strip():
        yield Finding(
            "cfg.E008",
            "EMAIL_HOST",
            "EMAIL_BACKEND is SMTP but EMAIL_HOST is empty.",
            "Set EMAIL_HOST to the SMTP relay.",
        )


def _cache(ns):
    caches = _get(ns, "CACHES") or {}
    backend = str((caches.get("default") or {}).get("BACKEND", ""))
    if not backend or backend.endswith(("LocMemCache", "DummyCache")):
        yield Finding(
            "cfg.E009",
            "CACHES",
            "The default cache is per-process: throttles, lockout and session revocation stop "
            "being shared between workers (AUTH_BLUEPRINT § 17.4).",
            "Point CACHE_URL at Redis (or another shared cache).",
        )


def _database(ns):
    databases = _get(ns, "DATABASES") or {}
    engine = str((databases.get("default") or {}).get("ENGINE", ""))
    if not engine or "sqlite" in engine:
        yield Finding(
            "cfg.E010",
            "DATABASES",
            "The default database is SQLite or not configured (ADR-0005: SQLite is for "
            "development only).",
            "Set DATABASE_URL to the production PostgreSQL database.",
        )


def _frontend_url(ns):
    split = urlsplit(str(_get(ns, "FRONTEND_BASE_URL", "") or "").strip())
    if split.scheme.lower() != "https" or not split.hostname or _is_loopback_host(split.hostname):
        yield Finding(
            "cfg.E011",
            "FRONTEND_BASE_URL",
            "FRONTEND_BASE_URL is not an https:// URL on a real host: emailed links would point "
            "at plain HTTP or at the recipient's own machine.",
            "Set FRONTEND_BASE_URL to the public https:// address of the frontend.",
        )


def _throttling(ns):
    rest = _get(ns, "REST_FRAMEWORK", {}) or {}
    if not rest.get("DEFAULT_THROTTLE_CLASSES"):
        yield Finding(
            "cfg.E012",
            "REST_FRAMEWORK",
            "REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] is empty: the API has no rate limit.",
            "Restore the default throttle classes.",
        )


def _mfa_key(ns):
    key = _get(ns, "MFA_ENCRYPTION_KEY", "")
    if not isinstance(key, str) or not key.strip():
        yield Finding(
            "cfg.W008",
            "MFA_ENCRYPTION_KEY",
            "MFA_ENCRYPTION_KEY is empty: MFA unavailable (setup answers 503).",
            "Generate a Fernet key to offer two-factor authentication.",
        )
        return
    try:
        from cryptography.fernet import Fernet

        Fernet(key.strip())
    except Exception:  # noqa: BLE001 — any parse failure is the finding; the value is never shown
        yield Finding(
            "cfg.E013",
            "MFA_ENCRYPTION_KEY",
            "MFA_ENCRYPTION_KEY is set but is not a valid Fernet key.",
            "Generate one with cryptography.fernet.Fernet.generate_key().",
        )


def _app_env(ns):
    value = _get(ns, "APP_ENV", "")
    if not isinstance(value, str) or not value.strip():
        yield Finding(
            "cfg.E014",
            "APP_ENV",
            "APP_ENV is unset: the environment is unknown, so it is treated as production.",
            "Set APP_ENV (production, staging, …; development/local/test/ci are non-production).",
        )


def _log_format(ns):
    value = _get(ns, "LOG_FORMAT", "")
    if not isinstance(value, str) or value.strip().lower() != "json":
        yield Finding(
            "cfg.E015",
            "LOG_FORMAT",
            "LOG_FORMAT is not json: production logs must be structured (OBSERVABILITY.md § 2).",
            "Set LOG_FORMAT=json.",
        )


def _hsts(ns):
    if not _get(ns, "SECURE_HSTS_SECONDS", 0):
        yield Finding(
            "cfg.W001",
            "SECURE_HSTS_SECONDS",
            "HSTS is off: a first visit over plain HTTP can be downgraded.",
            "Set SECURE_HSTS_SECONDS once HTTPS is confirmed everywhere.",
        )


def _proxy(ns):
    if _get(ns, "SECURE_PROXY_SSL_HEADER") and _get(ns, "TRUSTED_PROXY_COUNT", 0) == 0:
        yield Finding(
            "cfg.W002",
            "TRUSTED_PROXY_COUNT",
            "SECURE_PROXY_SSL_HEADER says the app is behind a proxy, but TRUSTED_PROXY_COUNT is "
            "0: every client shares the proxy's address for throttling and lockout (A20).",
            "Set TRUSTED_PROXY_COUNT to the number of proxies in front of the app.",
        )


def _admin(ns):
    if _get(ns, "ADMIN_ENABLED", False):
        yield Finding(
            "cfg.W004",
            "ADMIN_ENABLED",
            "The Django admin is enabled: a second authentication and authorization system "
            "beside the API's (AUTH_BLUEPRINT Ch. 20).",
            "Set ADMIN_ENABLED=False unless it is needed.",
        )


def _fallbacks(ns):
    fallbacks = [v for v in _as_list(_get(ns, "JWT_SIGNING_KEY_FALLBACKS", [])) if v]
    if fallbacks:
        yield Finding(
            "cfg.W005",
            "JWT_SIGNING_KEY_FALLBACKS",
            "JWT_SIGNING_KEY_FALLBACKS is not empty: a key rotation is in progress.",
            "Remove the old key once REFRESH_TOKEN_LIFETIME has passed (AUTH_BLUEPRINT § 19.3).",
        )


# cfg.E001 (dev.py/test.py loaded in production) is omitted: this repository has one settings
# module, and APP_ENV classifies it. cfg.W003 (identity defaults) waits for the identity settings
# of CONFIGURATION.md § 7, cfg.W006 (.env read in production) for settings to record whether a
# file was read, and cfg.W007 (public schema) for a schema-visibility setting. Each lands with
# the setting it inspects.
RULES = (
    _app_env,
    _debug,
    _secrets,
    _shared_secrets,
    _allowed_hosts,
    _origins,
    _cookies,
    _email,
    _cache,
    _database,
    _frontend_url,
    _throttling,
    _mfa_key,
    _log_format,
    _hsts,
    _proxy,
    _admin,
    _fallbacks,
)


def audit(ns: Mapping[str, Any]) -> tuple[list[Finding], list[Finding]]:
    """(problems, warnings) for a settings namespace. Never raises on a malformed value."""
    findings: list[Finding] = []
    for rule in RULES:
        try:
            findings.extend(rule(ns))
        except Exception:  # noqa: BLE001 — a rule that cannot read its setting refuses, loudly
            findings.append(
                Finding(
                    f"cfg.E000.{rule.__name__.strip('_')}",
                    rule.__name__.strip("_"),
                    f"The {rule.__name__.strip('_')} rule could not read its settings.",
                    "Check the setting's type against config/settings.py.",
                )
            )
    problems = [f for f in findings if f.is_problem]
    warnings = [f for f in findings if not f.is_problem]
    return problems, warnings


def render(title: str, problems: list[Finding], warnings: list[Finding]) -> str:
    lines = [f"{title}: {len(problems)} problem(s), {len(warnings)} warning(s)."]
    if problems:
        lines.append("Problems (refuse boot in a production-like APP_ENV):")
        for n, f in enumerate(problems, 1):
            lines.append(f"  {n}. [{f.code}] {f.key}: {f.message}")
            lines.append(f"     Fix: {f.fix}")
    if warnings:
        lines.append("Warnings:")
        for f in warnings:
            lines.append(f"  - [{f.code}] {f.key}: {f.message}")
            lines.append(f"    Fix: {f.fix}")
    return "\n".join(lines)


# Set only by this module's own __main__, in-process. Deliberately not an environment variable:
# an env switch that skips the refusal is one an operator can set in production.
_report_only = False


def enforce(ns: Mapping[str, Any]) -> None:
    """The last line of the settings module: refuse a bad production config, warn otherwise."""
    if _report_only:
        return
    problems, warnings = audit(ns)
    # Settings are not ready while they are being imported: classify the namespace's own value.
    if is_production_like(_get(ns, "APP_ENV", "") or ""):
        if problems:
            raise ImproperlyConfigured(render("Refusing to start", problems, warnings))
        _log(warnings)
    else:
        _log(problems + warnings)


def _log(findings: list[Finding]) -> None:
    for f in findings:
        logger.warning(
            "%s %s: %s Fix: %s",
            f.code,
            f.key,
            f.message,
            f.fix,
            extra={"cfg_code": f.code, "cfg_key": f.key},
        )


def main() -> int:
    """Print the report for DJANGO_SETTINGS_MODULE. Exit 1 when it would refuse to boot."""
    global _report_only
    module_name = os.environ.get("DJANGO_SETTINGS_MODULE")
    if not module_name:
        print("DJANGO_SETTINGS_MODULE is not set.", file=sys.stderr)
        return 2
    # Run as `python -m core.config_audit`, this file is __main__; the settings module imports
    # core.config_audit, a separate module object. Switch both off before importing settings.
    _report_only = True
    sys.modules.setdefault("core.config_audit", sys.modules[__name__])
    importlib.import_module("core.config_audit")._report_only = True

    namespace = vars(importlib.import_module(module_name))
    problems, warnings = audit(namespace)
    refuses = is_production_like(_get(namespace, "APP_ENV", "") or "") and bool(problems)
    title = "Would refuse to start" if refuses else "Configuration report"
    print(render(title, problems, warnings))
    return 1 if refuses else 0


if __name__ == "__main__":
    sys.exit(main())
