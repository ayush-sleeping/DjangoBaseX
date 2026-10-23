"""
Project identity: one name derives the rest (CONFIGURATION.md § 7, BUILD_ORDER 5.2).

The derivation runs in the REAL config/settings.py, imported in a fresh interpreter from a copy of
backend/ without any .env, so neither a developer's .env nor this process's settings can leak in.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.identity import (
    SHIPPED_COOKIE_PREFIX,
    SHIPPED_PRODUCT_NAME,
    SHIPPED_TAGLINE,
    cookie_prefix,
    product_slug,
    tagline,
)

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
IGNORE = shutil.ignore_patterns(
    ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "db.sqlite3", ".env"
)
DEVELOPMENT = {"APP_ENV": "development", "SECRET_KEY": "x" * 50, "JWT_SIGNING_KEY": "y" * 40}
PROBE = """
import json
from django.conf import settings
print(json.dumps({
    "name": settings.PRODUCT_NAME,
    "slug": settings.PRODUCT_SLUG,
    "domain": settings.PRIMARY_DOMAIN,
    "tagline": settings.PRODUCT_TAGLINE,
    "issuer": settings.MFA_ISSUER,
    "from": settings.DEFAULT_FROM_EMAIL,
    "cookie": settings.AUTH_COOKIE_PREFIX,
    "session": settings.SESSION_COOKIE_NAME,
    "csrf": settings.CSRF_COOKIE_NAME,
    "cache": settings.CACHES["default"]["KEY_PREFIX"],
    "title": settings.SPECTACULAR_SETTINGS["TITLE"],
}))
"""


@pytest.fixture(scope="module")
def backend_copy(tmp_path_factory):
    copy = tmp_path_factory.mktemp("identity") / "backend"
    shutil.copytree(BACKEND, copy, ignore=IGNORE)
    assert not (copy / ".env").exists()
    return copy


def derived(root: Path, **env: str) -> dict:
    clean = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "TMPDIR"}}
    clean |= {"DJANGO_SETTINGS_MODULE": "config.settings", "PYTHONPATH": str(root)}
    clean |= DEVELOPMENT | env
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=root, env=clean, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


# --- The rules, as pure functions ---------------------------------------------------------------


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Acme Portal", "acme-portal"),
        ("My Product_v2", "my-product-v2"),
        ("  --Ünïcode & Co.--  ", "n-code-co"),
        ("!!!", "product"),
        ("a" * 50, "a" * 36),
        ("x" * 35 + " y", "x" * 35),  # never ends on a '-' after truncation
    ],
)
def test_product_slug(name, slug):
    assert product_slug(name) == slug
    assert product_slug(slug) == slug  # a valid slug is a fixed point


def test_the_slug_rule_matches_setup_sh():
    """scripts/lib/project.sh::project_slug makes the per-checkout slug; the two must agree."""
    lib = REPO / "scripts" / "lib" / "project.sh"
    for name in ("Acme Portal", "My Product_v2", "a" * 50, "x" * 35 + " y"):
        result = subprocess.run(
            ["bash", "-c", f'. "{lib}"; project_slug "$1"', "_", name],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == product_slug(name), name


def test_cookie_prefix_and_the_shipped_defaults():
    assert cookie_prefix("acme-portal") == "acme_portal"
    assert SHIPPED_COOKIE_PREFIX == "unnamed_product"


def test_the_tagline_nags_only_while_the_name_is_the_default():
    assert tagline(SHIPPED_PRODUCT_NAME, "") == SHIPPED_TAGLINE
    assert tagline("Acme Portal", "") == ""
    assert tagline("Acme Portal", "Ship faster") == "Ship faster"


# --- The real settings --------------------------------------------------------------------------


def test_shipped_defaults_announce_themselves(backend_copy):
    d = derived(backend_copy)
    assert d["name"] == "Unnamed product"
    assert d["tagline"] == SHIPPED_TAGLINE
    assert d["domain"] == "localhost"
    assert d["from"] == "Unnamed product <no-reply@localhost>"  # bounces; impersonates nobody
    assert d["cookie"] == "unnamed_product"


def test_one_name_derives_every_value(backend_copy):
    d = derived(backend_copy, PRODUCT_NAME="Acme Portal", PRIMARY_DOMAIN="acme.test")
    assert d == {
        "name": "Acme Portal",
        "slug": "acme-portal",
        "domain": "acme.test",
        "tagline": "",
        "issuer": "Acme Portal",
        "from": "Acme Portal <no-reply@acme.test>",
        "cookie": "acme_portal",
        "session": "acme_portal_sessionid",
        "csrf": "acme_portal_csrftoken",
        "cache": "acme-portal",
        "title": "Acme Portal API",
    }


def test_changing_the_name_changes_every_derived_value(backend_copy):
    a = derived(backend_copy, PRODUCT_NAME="Acme Portal")
    b = derived(backend_copy, PRODUCT_NAME="Globex Desk")
    for key in ("issuer", "from", "cookie", "session", "csrf", "cache", "title"):
        assert a[key] != b[key], key


def test_explicit_overrides_win(backend_copy):
    d = derived(
        backend_copy,
        PRODUCT_NAME="Acme Portal",
        PRODUCT_SLUG="acme-dev-2",
        MFA_ISSUER="Acme",
        DEFAULT_FROM_EMAIL="Acme <help@acme.test>",
        AUTH_COOKIE_PREFIX="acme_checkout",
    )
    assert d["slug"] == "acme-dev-2"
    assert d["cache"] == "acme-dev-2"
    assert d["issuer"] == "Acme"
    assert d["from"] == "Acme <help@acme.test>"
    assert d["cookie"] == "acme_checkout"
    assert d["session"] == "acme_checkout_sessionid"


def test_an_explicit_slug_is_sanitised(backend_copy):
    d = derived(backend_copy, PRODUCT_SLUG="My Checkout!")
    assert d["slug"] == "my-checkout"
    assert d["cookie"] == "my_checkout"


def test_a_cache_url_prefix_is_not_overridden(backend_copy):
    d = derived(backend_copy, PRODUCT_NAME="Acme", CACHE_URL="locmemcache://?KEY_PREFIX=shared")
    assert d["cache"] == "shared"


# --- The API --------------------------------------------------------------------------------------


def test_public_config_serves_the_display_identity_only(client, settings):
    settings.PRODUCT_NAME = "Acme Portal"
    settings.PRODUCT_TAGLINE = "Ship faster"
    response = client.get("/api/public/config/")
    assert response.status_code == 200
    assert response.json() == {"product_name": "Acme Portal", "tagline": "Ship faster"}
