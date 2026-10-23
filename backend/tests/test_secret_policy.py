"""core.secret_policy: the formats it generates and the rules it judges by (CONFIGURATION.md § 5;
OPERATIONS.md § 2, § 21).

One definition serves the boot refusal (through core.config_audit), `manage.py generate_secret` and
scripts/setup.sh (through scripts/lib/envfile.py, which imports it before Django is installed).
These tests hold each format to what reads it, and hold the module to the standard library.
"""

import base64
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command

from core import config_audit, secret_policy
from core.secret_policy import (
    GENERATORS,
    JWT_KEY_MIN_LENGTH,
    SECRET_KEY_MIN_LENGTH,
    generate,
    is_placeholder,
    weak_reason,
)

BACKEND = Path(__file__).resolve().parents[1]
ROUNDS = 200
URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


def many(kind: str) -> list[str]:
    return [generate(kind) for _ in range(ROUNDS)]


# --- Each kind, in the format the code that reads it expects ------------------------------------


def test_django_keys_pass_the_audit_and_never_start_with_a_dollar():
    for key in many("django"):
        assert len(key) >= SECRET_KEY_MIN_LENGTH
        assert weak_reason(key, min_length=SECRET_KEY_MIN_LENGTH) is None
        # django-environ reads a leading `$` as a reference to another variable (TECH_DEBT DB-25).
        assert not key.startswith("$")
        assert URL_SAFE.match(key)


def test_jwt_keys_pass_the_audit():
    for key in many("jwt"):
        assert weak_reason(key, min_length=JWT_KEY_MIN_LENGTH) is None
        assert URL_SAFE.match(key)


def test_fernet_keys_construct_a_fernet_and_hold_32_bytes():
    for key in many("fernet"):
        Fernet(key)  # raises on a malformed key
        assert len(base64.urlsafe_b64decode(key)) == 32


def test_hex_secrets_are_48_lowercase_hex_characters():
    for value in many("hex"):
        assert re.fullmatch(r"[0-9a-f]{48}", value)


def test_passwords_are_24_url_safe_characters():
    for value in many("password"):
        assert len(value) == 24
        assert URL_SAFE.match(value)


def test_every_kind_is_covered_here():
    # A new kind without a format test above fails here first.
    assert set(GENERATORS) == {"django", "jwt", "fernet", "hex", "password"}


# --- generate() never hands back a value the audit would refuse ---------------------------------


def test_generate_retries_past_a_weak_value(monkeypatch):
    weak = "example" * 10  # long enough, but a known placeholder
    good = "A" + "bcdefghijklmnopqrstuvwxyz0123456789_-" * 2  # 75 chars, 38 distinct
    assert weak_reason(weak, min_length=SECRET_KEY_MIN_LENGTH) is not None
    assert weak_reason(good, min_length=SECRET_KEY_MIN_LENGTH) is None

    values = iter([weak, good])
    calls = []

    def fake():
        calls.append(1)
        return next(values)

    monkeypatch.setitem(secret_policy.GENERATORS, "django", fake)
    assert generate("django") == good
    assert len(calls) == 2  # it asked again, rather than returning the weak one


@pytest.mark.parametrize("kind", sorted(GENERATORS))
def test_generate_never_returns_what_setup_would_replace_next_run(kind, monkeypatch):
    # Every kind, not only those with a minimum length: a fernet key or a password that happened to
    # contain "example" would be "replaced placeholder" on the next run, silently rotating it.
    real = secret_policy.GENERATORS[kind]
    good = real()
    placeholder = "example" + good
    assert is_placeholder(placeholder, kind)
    assert not is_placeholder(good, kind)

    values = iter([placeholder, good])
    monkeypatch.setitem(secret_policy.GENERATORS, kind, lambda: next(values))
    assert generate(kind) == good


@pytest.mark.parametrize("kind", sorted(GENERATORS))
def test_a_generated_secret_is_never_a_placeholder(kind):
    assert not any(is_placeholder(value, kind) for value in many(kind))


def test_generate_rejects_an_unknown_kind():
    with pytest.raises(KeyError):
        generate("nope")


# --- The command line setup.sh uses -------------------------------------------------------------


def run_module(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "core.secret_policy", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("kind", sorted(GENERATORS))
def test_module_prints_exactly_one_secret(kind):
    result = run_module(kind)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0].strip()
    assert result.stdout == lines[0] + "\n"


@pytest.mark.parametrize("argv", [["nope"], [], ["hex", "jwt"]])
def test_module_refuses_a_bad_kind_with_exit_2(argv):
    result = run_module(*argv)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr


def test_module_imports_without_django():
    # setup.sh runs it with the system python3, before `uv sync` has installed anything.
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(BACKEND)!r}); "
        "import core.secret_policy; "
        "assert not any(m == 'django' or m.startswith('django.') for m in sys.modules), "
        "sorted(m for m in sys.modules if m.split('.')[0] == 'django')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


# --- The management command and the audit's re-exports ------------------------------------------


def test_generate_secret_command_prints_a_hex_secret():
    out = io.StringIO()
    call_command("generate_secret", kind="hex", stdout=out)
    assert re.fullmatch(r"[0-9a-f]{48}", out.getvalue().strip())


@pytest.mark.parametrize(
    "name",
    ["weak_reason", "GENERIC", "DISTINCTIVE", "SECRET_KEY_MIN_LENGTH", "JWT_KEY_MIN_LENGTH"],
)
def test_config_audit_re_exports_the_same_objects(name):
    # One definition: the audit's vocabulary IS the policy's, not a copy that can drift.
    assert getattr(config_audit, name) is getattr(secret_policy, name)
