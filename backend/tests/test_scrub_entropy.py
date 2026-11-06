"""
The high-entropy backstop (TECH_DEBT DB-51; OBSERVABILITY.md § 3), proven with seeded generators.

The contract: secrets travel by KEY (structured fields, headers, query parameters), where redaction
is exact. Detecting a bare secret in prose is a backstop, with a guarantee per band:
  band 1, 28+ characters (and pure hex of 32+): 0 misses, measured here over 50,000 tokens per kind;
  band 2, 20-27 characters: caught when a secret word precedes it ("reset token …", "api_key=…");
          otherwise best effort, at the residual rate measured here and stated below.

SEED was fixed before anything was measured, and is never changed to make a run pass. Tokens come
from random.Random(SEED).randbytes(), the same distribution as the secrets/uuid/base64 functions
products call.
"""

import base64
import random
import time
import uuid

import pytest

from core.observability.scrub import REDACTED, default_rules, looks_secret, scrub

SEED = 20261106
PER_KIND = 50_000
BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generators(rng: random.Random) -> dict:
    b = rng.randbytes
    return {
        # band 1
        "token_urlsafe(32)": lambda: base64.urlsafe_b64encode(b(32)).rstrip(b"=").decode(),
        "token_urlsafe(48)": lambda: base64.urlsafe_b64encode(b(48)).rstrip(b"=").decode(),
        "token_hex(16)": lambda: b(16).hex(),
        "token_hex(32)": lambda: b(32).hex(),
        "uuid4().hex": lambda: uuid.UUID(bytes=b(16), version=4).hex,
        "b64encode(21 bytes)": lambda: base64.b64encode(b(21)).decode(),
        "b64encode(32 bytes)": lambda: base64.b64encode(b(32)).decode(),
        "base32 TOTP secret": lambda: "".join(BASE32[x % 32] for x in b(32)),
        # band 2
        "token_urlsafe(16)": lambda: base64.urlsafe_b64encode(b(16)).rstrip(b"=").decode(),
        "b64encode(16 bytes)": lambda: base64.b64encode(b(16)).decode(),
        "b64encode(18 bytes)": lambda: base64.b64encode(b(18)).decode(),
    }


BAND_1 = (
    "token_urlsafe(32)",
    "token_urlsafe(48)",
    "token_hex(16)",
    "token_hex(32)",
    "uuid4().hex",
    "b64encode(21 bytes)",
    "b64encode(32 bytes)",
    "base32 TOTP secret",
)
BAND_2 = ("token_urlsafe(16)", "b64encode(16 bytes)", "b64encode(18 bytes)")
# Prose with no secret word anywhere near the token.
PLAIN = (
    "refresh failed for {t}",
    "invite link used: {t} by user 42",
    "value was ({t}), rotated",
    "{t}",
    "Set header X-Api to {t} and retry",
)
WITH_SECRET_WORD = (
    "reset token {t} sent",
    "api_key={t}",
    "password is {t}",
    "Authorization: Bearer {t}",
    "session: '{t}'",
    "csrf {t}",
    'jwt="{t}"',
    "signature ({t})",
)
# Band 2's measured contextless misses on SEED (PER_KIND each). Measured once, recorded here; a
# change in the detector that raises any of them fails the test and must be justified.
BAND_2_CONTEXTLESS_MISSES = {
    "token_urlsafe(16)": 2,
    "b64encode(16 bytes)": 3,
    "b64encode(18 bytes)": 2,
}


def misses(kind: str, sentences, count: int) -> list[str]:
    rules = default_rules()
    make = generators(random.Random(f"{SEED}:{kind}"))[kind]
    missed = []
    for i in range(count):
        token = make()
        if token in rules.scrub_text(sentences[i % len(sentences)].format(t=token)):
            missed.append(token)
    return missed


@pytest.mark.parametrize("kind", BAND_1)
def test_band_1_is_caught_in_prose_with_no_context(kind):
    assert misses(kind, PLAIN, PER_KIND) == []


@pytest.mark.parametrize("kind", BAND_1 + BAND_2)
def test_every_kind_is_caught_after_a_secret_word(kind):
    assert misses(kind, WITH_SECRET_WORD, 10_000) == []


@pytest.mark.parametrize("kind", BAND_2)
def test_band_2_without_context_stays_within_its_measured_rate(kind):
    found = misses(kind, PLAIN, PER_KIND)
    assert len(found) <= BAND_2_CONTEXTLESS_MISSES[kind], found


# --- No over-redaction --------------------------------------------------------------------------

UNTOUCHED = (
    # CamelCase identifiers, short and long
    "SessionAuthenticationMiddleware2",
    "ArrayMaxLengthValidator",
    "ForeignKeyRawIdWidget",
    "BlockingZSetPopResponse",
    "DjangoFilterBackendWithPagination",
    "ImproperlyConfiguredExceptionHandler",
    # dotted Python paths, job names, settings keys
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.observability.request_id.RequestIdMiddleware",
    "users.auth_cleanup",
    "operations.queue.stall_threshold_minutes",
    # URLs without credentials, file paths
    "https://example.com/api/users/?page=2&ordering=-created_at",
    "https://docs.example.com/en/stable/topics/async/background-tasks/",
    "/var/lib/postgresql/data/pg_wal/archive_status",
    "backend/core/management/commands/sync_schedules.py",
    # long English words and snake/kebab case
    "counterrevolutionaries internationalization",
    "very_long_function_name_with_many_words",
    "sync-schedules-from-the-registry-on-migrate",
    "DEFAULT_AUTO_FIELD_FOR_EVERY_APP_CONFIG",
    # timestamps and readable ids
    "2026-11-06T07:21:03.123456+00:00",
    "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "/api/users/3fa85f64-5717-4562-b3fc-2c963f66afa6/roles/",
    "commit 9fceb02d0ae598e95dc970b74767f19372d61af8",
)


@pytest.mark.parametrize("text", UNTOUCHED)
def test_ordinary_long_strings_are_untouched(text):
    assert default_rules().scrub_text(text) == text


# The honest cost, measured on Django, DRF and Celery source (tests excluded): 16 of 86 mixed-case
# runs of 28+ characters (6.7% across all installed packages) and 22 of 509 of 20-27 characters
# are redacted, mostly alphabet constants and C-API names like these. By design.
REDACTED_BY_DESIGN = (
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "GEOSWKBWriter_getIncludeSRID",
    "8a477f597d28d172789f06886806bc55",  # bare 32-hex: indistinguishable from a token
    "9fceb02d0ae598e95dc970b74767f19372d61af8",  # an unlabelled 40-hex SHA
)


@pytest.mark.parametrize("text", REDACTED_BY_DESIGN)
def test_band_1_redacts_these_by_design(text):
    assert default_rules().scrub_text(text) == REDACTED


def test_a_secret_word_without_a_token_redacts_nothing():
    for text in ("the session expired", "invalid csrf token", "api_key missing", "code=404"):
        assert default_rules().scrub_text(text) == text


# --- Correlation ids ------------------------------------------------------------------------------


def test_correlation_ids_under_their_keys_stay_readable():
    rid = uuid.UUID(bytes=random.Random(SEED).randbytes(16), version=4).hex
    record = {"request_id": rid, "headers": {"X-Request-ID": rid}, "task_id": str(uuid.UUID(rid))}
    assert scrub(record) == record


def test_a_non_id_value_under_a_correlation_key_is_still_scrubbed():
    token = generators(random.Random(SEED))["token_urlsafe(32)"]()
    assert scrub({"request_id": f"x {token}"}) == {"request_id": f"x {REDACTED}"}


def test_a_request_id_in_prose_is_redacted_like_any_32_hex():
    # The contract: ids travel by key. In prose a uuid4().hex is indistinguishable from a token.
    rid = uuid.UUID(bytes=random.Random(SEED).randbytes(16), version=4).hex
    assert default_rules().scrub_text(f"request {rid} failed") == f"request {REDACTED} failed"


def test_looks_secret_matches_the_text_rule():
    token = generators(random.Random(SEED))["token_urlsafe(32)"]()
    assert looks_secret(token) and not looks_secret("SessionAuthenticationMiddleware2")


# --- Linear time -------------------------------------------------------------------------------

ONE_MB = 1_000_000


@pytest.mark.parametrize(
    "shape",
    ["one_run", "mixed_prose", "near_misses"],
)
def test_a_1_mb_line_scrubs_in_linear_time(shape):
    rng = random.Random(SEED)
    if shape == "one_run":  # a single 1 MB candidate run
        line = base64.b64encode(rng.randbytes(ONE_MB * 3 // 4)).decode()
    elif shape == "mixed_prose":
        token = generators(rng)["token_urlsafe(32)"]
        line = " ".join(f"user 42 used {token()} at /api/x/" for _ in range(ONE_MB // 64))
    else:  # runs one character short of a candidate, and '=' runs: backtracking bait
        line = ("Ab1-" * 4 + "x" * 3 + " " + "=" * 30 + " ") * (ONE_MB // 50)
    started = time.perf_counter()
    default_rules().scrub_text(line)
    elapsed = time.perf_counter() - started
    assert elapsed < 10.0, f"{shape}: {elapsed:.2f}s for {len(line):,} characters"
