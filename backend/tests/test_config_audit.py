"""Boot refusal at settings import (CONFIGURATION.md § 5). The valid configuration is tested FIRST:
a validator that rejects everything is trivially "safe" and useless."""

import logging
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

from core import config_audit
from core.config_audit import Finding, audit, enforce, render, weak_reason

BACKEND = Path(__file__).resolve().parents[1]


def valid_production() -> dict:
    """A correct production namespace: every rule satisfied, nothing worth a warning."""
    return {
        "APP_ENV": "production",
        "DEBUG": False,
        "SECRET_KEY": secrets.token_urlsafe(64),
        "JWT_SIGNING_KEY": secrets.token_urlsafe(48),
        "JWT_SIGNING_KEY_FALLBACKS": [],
        "FIELD_ENCRYPTION_KEYS": [Fernet.generate_key().decode()],
        "ALLOWED_HOSTS": ["api.acme.test"],
        "CORS_ALLOW_CREDENTIALS": True,
        "CORS_ALLOWED_ORIGINS": ["https://app.acme.test"],
        "CSRF_TRUSTED_ORIGINS": ["https://app.acme.test"],
        "AUTH_COOKIE_SECURE": True,
        "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "EMAIL_HOST": "smtp.acme.test",
        "CACHES": {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
        "DATABASES": {"default": {"ENGINE": "django.db.backends.postgresql"}},
        "FRONTEND_BASE_URL": "https://app.acme.test",
        "REST_FRAMEWORK": {"DEFAULT_THROTTLE_CLASSES": ["x.AnonRateThrottle"]},
        "LOG_FORMAT": "json",
        "SECURE_HSTS_SECONDS": 31_536_000,
        "SECURE_PROXY_SSL_HEADER": None,
        "TRUSTED_PROXY_COUNT": 0,
        "ADMIN_ENABLED": False,
        "PRODUCT_NAME": "Acme Portal",
        "PRIMARY_DOMAIN": "acme.test",
    }


# --- First: a correct production configuration boots --------------------------------------------


def test_valid_production_config_boots(caplog):
    ns = valid_production()
    assert audit(ns) == ([], [])
    with caplog.at_level(logging.WARNING, logger="core.config_audit"):
        enforce(ns)  # does not raise
    assert caplog.records == []


# --- One rule at a time -------------------------------------------------------------------------

LOCALHOST = "http://localhost:3000"

CASES = [
    # (id, changes, expected code, expected key)
    ("debug", {"DEBUG": True}, "cfg.E002", "DEBUG"),
    ("secret-placeholder", {"SECRET_KEY": "change-me" + "Zq9" * 20}, "cfg.E003", "SECRET_KEY"),
    ("secret-short", {"SECRET_KEY": secrets.token_urlsafe(20)}, "cfg.E003", "SECRET_KEY"),
    ("secret-generic", {"SECRET_KEY": "Password"}, "cfg.E003", "SECRET_KEY"),
    ("secret-repetitive", {"SECRET_KEY": "abcdefghij" * 6}, "cfg.E003", "SECRET_KEY"),
    ("jwt-empty", {"JWT_SIGNING_KEY": ""}, "cfg.E003", "JWT_SIGNING_KEY"),
    ("jwt-short", {"JWT_SIGNING_KEY": secrets.token_urlsafe(16)}, "cfg.E003", "JWT_SIGNING_KEY"),
    (
        "secret-equals-jwt",
        {"JWT_SIGNING_KEY": "SAME"},  # filled in below with SECRET_KEY's value
        "cfg.E004",
        "SECRET_KEY, JWT_SIGNING_KEY",
    ),
    ("hosts-empty", {"ALLOWED_HOSTS": []}, "cfg.E005", "ALLOWED_HOSTS"),
    ("hosts-wildcard", {"ALLOWED_HOSTS": ["api.acme.test", "*"]}, "cfg.E005", "ALLOWED_HOSTS"),
    ("cors-wildcard", {"CORS_ALLOWED_ORIGINS": ["*"]}, "cfg.E006", "CORS_ALLOWED_ORIGINS[0]"),
    (
        "cors-http",
        {"CORS_ALLOWED_ORIGINS": ["http://app.acme.test"]},
        "cfg.E006",
        "CORS_ALLOWED_ORIGINS[0]",
    ),
    (
        "csrf-localhost",
        {"CSRF_TRUSTED_ORIGINS": ["https://localhost"]},
        "cfg.E006",
        "CSRF_TRUSTED_ORIGINS[0]",
    ),
    (
        "csrf-127",
        {"CSRF_TRUSTED_ORIGINS": ["https://127.0.0.1:8443"]},
        "cfg.E006",
        "CSRF_TRUSTED_ORIGINS[0]",
    ),
    (
        "csrf-ipv6",
        {"CSRF_TRUSTED_ORIGINS": ["https://[::1]"]},
        "cfg.E006",
        "CSRF_TRUSTED_ORIGINS[0]",
    ),
    ("cors-all", {"CORS_ALLOW_ALL_ORIGINS": True}, "cfg.E006", "CORS_ALLOW_ALL_ORIGINS"),
    ("cookie-insecure", {"AUTH_COOKIE_SECURE": False}, "cfg.E007", "AUTH_COOKIE_SECURE"),
    (
        "email-console",
        {"EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"},
        "cfg.E008",
        "EMAIL_BACKEND",
    ),
    (
        "email-locmem",
        {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
        "cfg.E008",
        "EMAIL_BACKEND",
    ),
    ("smtp-no-host", {"EMAIL_HOST": ""}, "cfg.E008", "EMAIL_HOST"),
    (
        "cache-locmem",
        {"CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}},
        "cfg.E009",
        "CACHES",
    ),
    (
        "cache-dummy",
        {"CACHES": {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}},
        "cfg.E009",
        "CACHES",
    ),
    (
        "db-sqlite",
        {"DATABASES": {"default": {"ENGINE": "django.db.backends.sqlite3"}}},
        "cfg.E010",
        "DATABASES",
    ),
    (
        "frontend-http",
        {"FRONTEND_BASE_URL": "http://app.acme.test"},
        "cfg.E011",
        "FRONTEND_BASE_URL",
    ),
    (
        "frontend-localhost",
        {"FRONTEND_BASE_URL": "https://localhost:3000"},
        "cfg.E011",
        "FRONTEND_BASE_URL",
    ),
    (
        "no-throttles",
        {"REST_FRAMEWORK": {"DEFAULT_THROTTLE_CLASSES": []}},
        "cfg.E012",
        "REST_FRAMEWORK",
    ),
    (
        "mfa-not-fernet",
        {"FIELD_ENCRYPTION_KEYS": ["not-a-fernet-key"]},
        "cfg.E013",
        "FIELD_ENCRYPTION_KEYS",
    ),
    ("log-text", {"LOG_FORMAT": "text"}, "cfg.E015", "LOG_FORMAT"),
    ("hsts-off", {"SECURE_HSTS_SECONDS": 0}, "cfg.W001", "SECURE_HSTS_SECONDS"),
    (
        "proxy-mismatch",
        {"SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https")},
        "cfg.W002",
        "TRUSTED_PROXY_COUNT",
    ),
    ("identity-name", {"PRODUCT_NAME": "Unnamed product"}, "cfg.W003", "PRODUCT_NAME"),
    ("identity-name-unset", {"PRODUCT_NAME": ""}, "cfg.W003", "PRODUCT_NAME"),
    ("identity-domain", {"PRIMARY_DOMAIN": "localhost"}, "cfg.W003", "PRIMARY_DOMAIN"),
    ("admin-on", {"ADMIN_ENABLED": True}, "cfg.W004", "ADMIN_ENABLED"),
    (
        "rotation",
        {"JWT_SIGNING_KEY_FALLBACKS": [secrets.token_urlsafe(48)]},
        "cfg.W005",
        "JWT_SIGNING_KEY_FALLBACKS",
    ),
    (
        "keyring-empty-dev",
        {"APP_ENV": "development", "FIELD_ENCRYPTION_KEYS": []},
        "cfg.W008",
        "FIELD_ENCRYPTION_KEYS",
    ),
]


@pytest.mark.parametrize("changes, code, key", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_each_rule_alone(changes, code, key):
    ns = valid_production()
    ns.update(changes)
    if ns.get("JWT_SIGNING_KEY") == "SAME":
        ns["JWT_SIGNING_KEY"] = ns["SECRET_KEY"]
    problems, warnings = audit(ns)
    findings = problems + warnings
    assert [(f.code, f.key) for f in findings] == [(code, key)]
    assert (findings[0] in problems) == code.startswith("cfg.E")


@pytest.mark.parametrize(
    "missing, code",
    [("APP_ENV", "cfg.E014"), ("LOG_FORMAT", "cfg.E015"), ("ALLOWED_HOSTS", "cfg.E005")],
)
def test_a_missing_setting_is_a_problem_not_a_pass(missing, code):
    ns = valid_production()
    del ns[missing]
    problems, _ = audit(ns)
    assert [f.code for f in problems] == [code]


def test_a_blank_app_env_is_unset():
    ns = valid_production()
    ns["APP_ENV"] = "  "
    assert [f.code for f in audit(ns)[0]] == ["cfg.E014"]


def test_each_fallback_key_is_checked_for_strength_and_reuse():
    ns = valid_production()
    good = secrets.token_urlsafe(48)
    ns["JWT_SIGNING_KEY_FALLBACKS"] = [good, "short", ns["JWT_SIGNING_KEY"]]
    problems, warnings = audit(ns)
    assert ("cfg.E003", "JWT_SIGNING_KEY_FALLBACKS[1]") in {(f.code, f.key) for f in problems}
    assert ("cfg.E004", "JWT_SIGNING_KEY, JWT_SIGNING_KEY_FALLBACKS[2]") in {
        (f.code, f.key) for f in problems
    }
    assert [f.code for f in warnings] == ["cfg.W005"]


def test_an_encryption_key_equal_to_another_secret_is_refused():
    ns = valid_production()
    ns["JWT_SIGNING_KEY"] = ns["FIELD_ENCRYPTION_KEYS"][0]
    assert ("cfg.E004", "JWT_SIGNING_KEY, FIELD_ENCRYPTION_KEYS[0]") in {
        (f.code, f.key) for f in audit(ns)[0]
    }
    assert ("cfg.E013", "FIELD_ENCRYPTION_KEYS") in {(f.code, f.key) for f in audit(ns)[0]}


def test_an_empty_keyring_is_an_error_in_production_and_a_warning_in_development():
    ns = valid_production()
    ns["FIELD_ENCRYPTION_KEYS"] = []
    assert ("cfg.E013", "FIELD_ENCRYPTION_KEYS") in {(f.code, f.key) for f in audit(ns)[0]}


def test_origins_are_only_checked_when_credentials_are_allowed():
    ns = valid_production()
    ns["CORS_ALLOW_CREDENTIALS"] = False
    ns["CORS_ALLOWED_ORIGINS"] = ["*"]
    assert audit(ns) == ([], [])


# --- All at once ---------------------------------------------------------------------------------


def test_all_problems_reported_together():
    ns = valid_production()
    ns.update(DEBUG=True, ALLOWED_HOSTS=[], AUTH_COOKIE_SECURE=False, LOG_FORMAT="text")
    with pytest.raises(ImproperlyConfigured) as exc:
        enforce(ns)
    text = str(exc.value)
    for code in ("cfg.E002", "cfg.E005", "cfg.E007", "cfg.E015"):
        assert code in text
    assert "4 problem(s)" in text
    assert text.count("Fix:") == 4


def test_render_numbers_problems_and_lists_warnings():
    problem = Finding("cfg.E002", "DEBUG", "DEBUG is on.", "Set DEBUG=False.")
    warning = Finding("cfg.W004", "ADMIN_ENABLED", "Admin on.", "Turn it off.")
    assert render("Refusing to start", [problem], [warning]).splitlines() == [
        "Refusing to start: 1 problem(s), 1 warning(s).",
        "Problems (refuse boot in a production-like APP_ENV):",
        "  1. [cfg.E002] DEBUG: DEBUG is on.",
        "     Fix: Set DEBUG=False.",
        "Warnings:",
        "  - [cfg.W004] ADMIN_ENABLED: Admin on.",
        "    Fix: Turn it off.",
    ]


# --- Where it refuses, and where it only warns ----------------------------------------------------


@pytest.mark.parametrize("app_env", ["production", "Production", "staging", "qa", ""])
def test_production_like_environments_refuse(app_env):
    ns = valid_production()
    ns.update(APP_ENV=app_env, DEBUG=True)
    with pytest.raises(ImproperlyConfigured, match="cfg.E002"):
        enforce(ns)


@pytest.mark.parametrize("app_env", ["development", "local", "test", "ci"])
def test_other_environments_log_every_finding_and_start(app_env, caplog):
    ns = valid_production()
    ns.update(APP_ENV=app_env, DEBUG=True, ADMIN_ENABLED=True)
    with caplog.at_level(logging.WARNING, logger="core.config_audit"):
        enforce(ns)
    assert [r.cfg_code for r in caplog.records] == ["cfg.E002", "cfg.W004"]


def test_production_logs_its_warnings_when_it_starts(caplog):
    ns = valid_production()
    ns["ADMIN_ENABLED"] = True
    with caplog.at_level(logging.WARNING, logger="core.config_audit"):
        enforce(ns)
    assert [r.cfg_code for r in caplog.records] == ["cfg.W004"]


def test_a_rule_that_cannot_read_its_setting_refuses_rather_than_crashing():
    ns = valid_production()
    ns["CACHES"] = "not-a-dict"
    problems, _ = audit(ns)
    assert [f.code for f in problems] == ["cfg.E000.cache"]


# --- Values never appear --------------------------------------------------------------------------

CANARY = "CanaryValue-7f3Q"


def test_no_value_in_any_message(caplog):
    canary_ns = valid_production()
    canary_ns.update(
        DEBUG=True,
        SECRET_KEY=CANARY,
        JWT_SIGNING_KEY=CANARY,
        JWT_SIGNING_KEY_FALLBACKS=[CANARY, CANARY + "x"],
        FIELD_ENCRYPTION_KEYS=[CANARY],
        ALLOWED_HOSTS=[],
        CORS_ALLOWED_ORIGINS=[f"http://{CANARY}.test", "*"],
        CSRF_TRUSTED_ORIGINS=[f"https://localhost/{CANARY}"],
        EMAIL_BACKEND=f"console.{CANARY}",
        CACHES={"default": {"BACKEND": f"{CANARY}.LocMemCache"}},
        DATABASES={"default": {"ENGINE": f"sqlite.{CANARY}"}},
        FRONTEND_BASE_URL=f"http://{CANARY}",
        LOG_FORMAT=CANARY,
        APP_ENV="",
    )
    problems, warnings = audit(canary_ns)
    assert len(problems) >= 12  # the canary really went through most rules

    with pytest.raises(ImproperlyConfigured) as exc:
        enforce(canary_ns)
    canary_ns["APP_ENV"] = "development"
    with caplog.at_level(logging.WARNING, logger="core.config_audit"):
        enforce(canary_ns)

    texts = [str(exc.value), caplog.text, render("x", problems, warnings)]
    texts += [repr(f) for f in problems + warnings]
    for text in texts:
        assert CANARY not in text


# --- Secret strength (§ 5) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, reason",
    [
        (None, "is empty"),
        ("   ", "is empty"),
        ("secret", "is a generic placeholder word"),
        ("ADMIN", "is a generic placeholder word"),
        ("changeme" * 4, "contains a known placeholder"),  # equality would have let this through
        ("prefix-django-insecure-" + secrets.token_urlsafe(40), "contains a known placeholder"),
        ("Your-Key-" + secrets.token_urlsafe(50), "contains a known placeholder"),
        ("aB3" * 5, "is shorter than 50 characters"),
        ("abcdefghijk" * 6, "has fewer than 12 distinct characters"),
    ],
    ids=[
        "none",
        "blank",
        "generic",
        "generic-case",
        "repeated-placeholder",
        "django-insecure",
        "your-",
        "short",
        "repetitive",
    ],
)
def test_weak_reason(value, reason):
    assert weak_reason(value, min_length=50) == reason


def test_honest_random_keys_pass_even_if_they_contain_short_words():
    for _ in range(50):
        key = secrets.token_urlsafe(64)
        assert weak_reason(key, min_length=50) is None
    assert weak_reason("test" + secrets.token_urlsafe(60), min_length=50) is None


# --- python -m core.config_audit ------------------------------------------------------------------


def _settings_module(tmp_path, **overrides) -> str:
    ns = valid_production()
    ns.update(overrides)
    lines = [f"{key} = {value!r}" for key, value in ns.items()]
    body = "\n".join(lines)
    (tmp_path / "audit_probe_settings.py").write_text(
        f"{body}\n\nfrom core.config_audit import enforce\n\nenforce(globals())\n"
    )
    return "audit_probe_settings"


def _run_report(tmp_path, module):
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": f"{BACKEND}:{tmp_path}",
        "DJANGO_SETTINGS_MODULE": module,
    }
    return subprocess.run(
        [sys.executable, "-m", "core.config_audit"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_report_command_prints_without_raising(tmp_path):
    module = _settings_module(tmp_path, DEBUG=True, ADMIN_ENABLED=True)
    result = _run_report(tmp_path, module)
    assert result.returncode == 1, result.stderr
    assert "Would refuse to start: 1 problem(s), 1 warning(s)." in result.stdout
    assert "[cfg.E002] DEBUG" in result.stdout
    assert "Traceback" not in result.stderr


def test_the_report_command_exits_0_for_a_good_config(tmp_path):
    result = _run_report(tmp_path, _settings_module(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "Configuration report: 0 problem(s), 0 warning(s)." in result.stdout


def test_the_report_only_switch_is_not_an_environment_variable():
    # An env switch that skips the refusal is one an operator could set in production.
    source = Path(config_audit.__file__).read_text()
    assert 'os.environ.get("DJANGO_SETTINGS_MODULE")' in source
    assert source.count("os.environ") == 1
