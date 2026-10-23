"""The one scrubber (OBSERVABILITY.md § 3)."""

import copy
import json
import secrets

import pytest
from django.conf import settings

from core.observability.scrub import (
    CIRCULAR,
    MAX_DEPTH,
    MAX_ITEMS,
    MAX_STRING,
    REDACTED,
    TRUNCATED,
    ScrubRules,
    default_rules,
    normalise_key,
    rules_as_json,
    scrub,
)

F = REDACTED
P = settings.AUTH_COOKIE_PREFIX  # the configured product's cookies (CONFIGURATION § 7)
JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
RANDOM = "Zq8mT2vK9pL3xW7nR4bY6cH1dF5gJ0sA"  # 32 chars, mixed: shaped like a generated secret


# --- Keys ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "PASSWORD",
        "PASS_WORD",
        "new_password",
        "newPassword",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "accessToken",
        "refresh-token",
        "id_token",
        "Authorization",
        "authorization",
        "HTTP_AUTHORIZATION",
        "Proxy-Authorization",
        "Cookie",
        "HTTP_COOKIE",
        "Set-Cookie",
        "csrf",
        "X-CSRF-Token",
        "csrftoken",
        "sessionid",
        "api_key",
        "apiKey",
        "apikey",
        "x-api-key",
        "X-API-KEY",
        "HTTP_X_API_KEY",
        "private_key",
        "otp",
        "mfa_code",
        "recovery_code",
        "mfa_token",
        # suffix rules
        "stripe_secret",
        "webhook_token",
        "db_password",
        "signing_key",
        # the auth cookies, plain and __Host- prefixed
        f"{P}_access",
        f"__Host-{P}_access",
        f"{P}_refresh",
        f"__Host-{P}_csrf",
        f"{P}_sessionid",
        f"{P}_csrftoken",
    ],
)
def test_sensitive_keys_are_redacted(key):
    assert scrub({key: "s3cr3t-value", "user_id": 7}) == {key: F, "user_id": 7}


@pytest.mark.parametrize(
    "key",
    [
        "token_count",  # the spec's own negative case: substring matching broke this before
        "max_tokens",
        "token_type",
        "tokenizer",
        "passport",
        "passport_number",
        "code",  # error.code must stay readable; `code` is only sensitive as a query parameter
        "error_code",
        "status_code",
        "cache_key",
        "sort_key",
        "public_key",
        "publicKey",
        "idempotency_key",
        "kid",
        "primary_key",
        "monkey",
        "keyboard",
        "secretary",
        "user_id",
        "email_verified",
        "api_key_id",
    ],
)
def test_ordinary_keys_stay_readable(key):
    assert scrub({key: "visible"}) == {key: "visible"}


def test_a_sensitive_key_redacts_whatever_it_holds():
    assert scrub({"password": {"nested": "x"}, "token": ["a", "b"], "secret": None}) == {
        "password": F,
        "token": F,
        "secret": F,
    }


def test_normalise_key():
    assert normalise_key("X-API-Key") == "x_api_key"
    assert normalise_key("apiKey") == "api_key"
    assert normalise_key("  Refresh.Token ") == "refresh_token"
    assert normalise_key(42) == "42"


def test_the_cookie_prefix_comes_from_the_rules():
    rules = ScrubRules(cookie_prefix="acme")
    assert scrub({"acme_refresh": "x", "dbx_refresh": "y"}, rules) == {
        "acme_refresh": F,
        "dbx_refresh": "y",
    }


def test_modules_can_extend_the_keys():
    rules = ScrubRules(extra_keys=frozenset({"card_number", "IBAN"}))
    assert scrub({"cardNumber": "4242", "iban": "GB00", "amount": 5}, rules) == {
        "cardNumber": F,
        "iban": F,
        "amount": 5,
    }


# --- Text ---------------------------------------------------------------------------------------


TEXT_CASES = [
    (f"Authorization: Bearer {JWT}", f"Authorization: Bearer {F}"),
    (f"sent bearer {RANDOM} upstream", f"sent bearer {F} upstream"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", f"Authorization: Basic {F}"),
    (f"token was {JWT}.", f"token was {F}."),
    (
        "postgres://app:hunter2@db.internal:5432/app",
        f"postgres://app:{F}@db.internal:5432/app",
    ),
    (
        "GET /cb?code=4/0AY0e&state=xyz&lang=en",
        f"GET /cb?code={F}&state={F}&lang=en",
    ),
    (
        "/reset-password?token=abc123DEF",
        f"/reset-password?token={F}",
    ),
    ("https://x.test/?Access_Token=abc&page=2", f"https://x.test/?Access_Token={F}&page=2"),
    (
        f"Cookie: {P}_access=abc.def; __Host-{P}_csrf=zzz; theme=dark",
        f"Cookie: {P}_access={F}; __Host-{P}_csrf={F}; theme=dark",
    ),
    (
        f"Cookie: {P}_sessionid=abc123; {P}_csrftoken=def456",
        f"Cookie: {P}_sessionid={F}; {P}_csrftoken={F}",
    ),
    ("sessionid=abc123; csrftoken=def456", f"sessionid={F}; csrftoken={F}"),
    ("login failed: password=hunter2 for x", f"login failed: password={F} for x"),
    ("{'new_password': 'hunter2', 'n': 1}", f"{{'new_password': '{F}', 'n': 1}}"),
    ("API_KEY: sk_live_abc", f"API_KEY: {F}"),
    (f"key {'ab12' * 16} rotated", f"key {F} rotated"),  # 64 hex characters
    (f"value {RANDOM} here", f"value {F} here"),
]


@pytest.mark.parametrize("text, expected", TEXT_CASES)
def test_secrets_inside_text(text, expected):
    assert scrub(text) == expected


@pytest.mark.parametrize("text, _", TEXT_CASES)
def test_scrubbing_twice_changes_nothing(text, _):
    once = scrub(text)
    assert scrub(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "tokenizer docs",
        "the passport office",
        "Passwords must be at least 12 characters.",
        "a secret santa",
        "bearer bonds are rare",
        "GET /api/users/?page=2&search=ann",
        "/api/users/3fa85f64-5717-4562-b3fc-2c963f66afa6/roles/",
        "commit 9fceb02d0ae598e95dc970b74767f19372d61af8",  # 40 hex: a git SHA, not a secret
        "SessionAuthenticationMiddleware2 failed",
        "django.core.mail.backends.smtp.EmailBackend",
        "error.code is invalid_mfa_code",
        "tokens_used=512 total",
        "user_id=42 email_verified=true",
    ],
)
def test_ordinary_text_is_untouched(text):
    assert scrub(text) == text


def test_json_inside_a_string_is_scrubbed_structurally():
    body = json.dumps({"email": "a@b.test", "password": "hunter2", "nested": {"token": "t"}})
    assert json.loads(scrub(body)) == {"email": "a@b.test", "password": F, "nested": {"token": F}}


def test_a_string_that_only_looks_like_json_falls_back_to_text_rules():
    assert scrub("{not json password=hunter2") == f"{{not json password={F}"


# --- Shape --------------------------------------------------------------------------------------


def test_nested_structures():
    value = {
        "request": {
            "headers": {"Authorization": "Bearer x", "Accept": "json"},
            "query": [("code", "abc"), ("page", "2")],
            "url": "https://x.test/cb?code=abc",
        },
        "events": [{"meta": {"refresh_token": "r"}, "msg": f"saw {JWT}"}],
    }
    assert scrub(value) == {
        "request": {
            "headers": {"Authorization": F, "Accept": "json"},
            "query": [("code", "abc"), ("page", "2")],  # a pair is not a key: kept
            "url": f"https://x.test/cb?code={F}",
        },
        "events": [{"meta": {"refresh_token": F}, "msg": f"saw {F}"}],
    }


def test_types_are_kept_for_lists_and_tuples():
    out = scrub({"a": [1, "x"], "b": (2, "y")})
    assert isinstance(out["a"], list) and isinstance(out["b"], tuple)


def test_the_input_is_never_mutated():
    value = {"password": "p", "list": [{"token": "t"}, f"Bearer {RANDOM}"], "t": ("secret=x",)}
    before = copy.deepcopy(value)
    scrub(value)
    assert value == before


def test_cycles_are_safe():
    a: dict = {"name": "a", "password": "p"}
    a["self"] = a
    loop: list = [1]
    loop.append(loop)
    assert scrub(a) == {"name": "a", "password": F, "self": CIRCULAR}
    assert scrub(loop) == [1, CIRCULAR]


def test_a_shared_child_that_is_not_a_cycle_is_scrubbed_twice():
    shared = {"token": "t", "n": 1}
    assert scrub({"a": shared, "b": shared}) == {
        "a": {"token": F, "n": 1},
        "b": {"token": F, "n": 1},
    }


def test_depth_is_capped_and_deep_values_become_truncated_not_passed_through():
    value: object = "password=hunter2"
    for _ in range(MAX_DEPTH + 5):
        value = [value]
    out = scrub(value)
    flat = json.dumps(out)
    assert "hunter2" not in flat
    assert TRUNCATED in flat


def test_containers_are_capped():
    out = scrub(list(range(MAX_ITEMS + 50)))
    assert len(out) == MAX_ITEMS + 1 and out[-1] == TRUNCATED
    big = scrub({f"k{i}": i for i in range(MAX_ITEMS + 3)})
    assert big[TRUNCATED] == 3


def test_long_strings_are_scrubbed_before_they_are_cut():
    text = "x" * (MAX_STRING - 10) + f" {JWT}"
    out = scrub(text)
    assert out.endswith(TRUNCATED)
    assert "eyJ" not in out


# --- Never raises ---------------------------------------------------------------------------------


class Exploding:
    def __str__(self):
        raise RuntimeError("no")


class Leaky:
    def __str__(self):
        return f"Leaky(password=hunter2, jwt={JWT})"


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        3.5,
        True,
        b"password=hunter2",
        bytearray(b"\xff\xfe broken utf8 token=abc"),
        memoryview(b"abc"),
        {1: "int key", None: "none key", ("t",): "tuple key"},
        {"s": {1, 2, 3}},
        Exploding(),
        Leaky(),
        object(),
        float("nan"),
    ],
)
def test_never_raises(value):
    scrub(value)


def test_bytes_are_decoded_and_scrubbed():
    assert scrub(b"password=hunter2") == f"password={F}"


def test_objects_are_scrubbed_as_their_string_form():
    assert "hunter2" not in scrub(Leaky()) and "eyJ" not in scrub(Leaky())
    assert scrub(Exploding()) == "[unrepresentable]"


def test_plain_scalars_pass_through_unchanged():
    from datetime import UTC, datetime
    from decimal import Decimal
    from uuid import uuid4

    values = [1, 2.5, True, None, Decimal("1.10"), datetime.now(UTC), uuid4()]
    assert scrub(values) == values


# --- The exported rules ---------------------------------------------------------------------------


def test_rules_export_is_json_and_complete():
    data = rules_as_json()
    assert json.loads(json.dumps(data)) == data
    assert data["replacement"] == F
    assert "password" in data["keys"] and f"{P}_access" in data["keys"]
    assert {p["name"] for p in data["text_patterns"]} >= {"jwt", "bearer", "query_param"}
    assert data["high_entropy"]["min_length"] == 32


def test_exported_patterns_avoid_python_only_syntax():
    # The frontend runs these same strings as JavaScript RegExp sources.
    for entry in [*rules_as_json()["text_patterns"], rules_as_json()["high_entropy"]]:
        for python_only in ("(?P<", "(?i)", "\\Z", "\\A", "(?#"):
            assert python_only not in entry["pattern"], entry


def test_default_rules_follow_the_settings_cookie_prefix(settings):
    default_rules.cache_clear()
    try:
        settings.AUTH_COOKIE_PREFIX = "acme"
        assert "acme_refresh" in default_rules().keys
    finally:
        default_rules.cache_clear()


def test_a_generated_secret_never_survives_a_realistic_log_record():
    token = secrets.token_urlsafe(32)
    record = {
        "msg": f"refresh failed for token {token}",
        "path": f"/api/auth/reset/?token={token}",
        "headers": {"Authorization": f"Bearer {token}"},
    }
    assert token not in json.dumps(scrub(record))
