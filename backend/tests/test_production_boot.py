"""
BUILD_ORDER 5.1 done-when, against the REAL config/settings.py (CONFIGURATION.md § 5):
- a valid production configuration imports (tested first: an audit that refuses everything is
  trivially "safe" and useless);
- importing with APP_ENV=production and the shipped .env.example values fails, naming every problem;
- APP_ENV=Production and APP_ENV=staging are both production-like.

Settings are imported in a fresh interpreter from a copy of backend/ without any .env file, so a
developer's .env cannot leak in and this process's already-configured Django proves nothing.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(
    ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "db.sqlite3", ".env"
)

VALID_PRODUCTION = {
    "APP_ENV": "production",
    "DEBUG": "False",
    "SECRET_KEY": "Qv7#pL2x!Rk9@mT4%wZ8^nB3&yH6*cF1(jD5)gS0-uA7_eK2+oN9=iM4",
    "JWT_SIGNING_KEY": "Jw8%Tq3!Lm6@Xr1#Vb5~Nc9^Kz2&Hd7*Pf4(Gs0)Ya3-Ue8_Wi1",
    "ALLOWED_HOSTS": "app.example.com",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
    "DATABASE_URL": "postgres://app:not-a-real-password-7Hq@db.internal:5432/app",
    "CACHE_URL": "redis://cache.internal:6379/0",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.example.com",
    "FRONTEND_BASE_URL": "https://app.example.com",
    "LOG_FORMAT": "json",
    "FIELD_ENCRYPTION_KEYS": "kH3t6pR2vX9qL5mN8bC1dF4gJ7wZ0sA2eY6uI9oP3rU=",
}
PROBE = "from django.conf import settings; settings.INSTALLED_APPS; print('IMPORTED')"


@pytest.fixture(scope="module")
def backend_copy(tmp_path_factory):
    copy = tmp_path_factory.mktemp("prodboot") / "backend"
    shutil.copytree(BACKEND, copy, ignore=IGNORE)
    assert not (copy / ".env").exists()
    return copy


def import_settings(root: Path, env: dict) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "TMPDIR"}}
    clean |= {"DJANGO_SETTINGS_MODULE": "config.settings", "PYTHONPATH": str(root), **env}
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=root,
        env=clean,
        capture_output=True,
        text=True,
        timeout=120,
    )


def env_example_values() -> dict:
    values = {}
    for line in (BACKEND / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_a_valid_production_configuration_boots(backend_copy):
    result = import_settings(backend_copy, VALID_PRODUCTION)
    assert result.returncode == 0 and "IMPORTED" in result.stdout, result.stderr[-3000:]


def test_the_shipped_example_refuses_to_boot_in_production_and_names_every_problem(backend_copy):
    result = import_settings(backend_copy, {**env_example_values(), "APP_ENV": "production"})
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    for code in ("cfg.E002", "cfg.E003", "cfg.E006", "cfg.E009", "cfg.E010"):
        assert code in result.stderr, f"{code} missing from the refusal"


@pytest.mark.parametrize("label", ["Production", "staging", "qa"])
def test_unusual_labels_are_secured_like_production(backend_copy, label):
    result = import_settings(backend_copy, {**VALID_PRODUCTION, "APP_ENV": label, "DEBUG": "True"})
    assert result.returncode != 0 and "cfg.E002" in result.stderr


def test_a_missing_app_env_is_refused(backend_copy):
    env = {k: v for k, v in VALID_PRODUCTION.items() if k != "APP_ENV"}
    result = import_settings(backend_copy, env)
    assert result.returncode != 0 and "cfg.E014" in result.stderr


def test_development_with_the_example_values_boots(backend_copy):
    # The fail-closed direction must not break the ordinary first run.
    values = {**env_example_values(), "APP_ENV": "development", "JWT_SIGNING_KEY": "dev-jwt-key-x"}
    result = import_settings(backend_copy, values)
    assert result.returncode == 0, result.stderr[-3000:]


def test_no_secret_value_appears_in_the_refusal(backend_copy):
    canary = "CANARYsecretValue0123456789abcdefghijklmnopqrstuvwxyz!@#"
    env = {**VALID_PRODUCTION, "DEBUG": "True", "SECRET_KEY": canary, "JWT_SIGNING_KEY": canary}
    result = import_settings(backend_copy, env)
    assert result.returncode != 0 and "cfg.E004" in result.stderr  # equal secrets
    assert canary not in result.stderr + result.stdout
