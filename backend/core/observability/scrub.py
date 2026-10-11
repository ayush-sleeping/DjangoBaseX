"""
One scrubber (OBSERVABILITY.md § 3). Every exit that writes data somewhere it is kept (the log
formatter, error reporting, the activity log's diffs) passes it through scrub() first. Two
scrubbers disagree, so there is exactly one rule set, and the frontend gets a generated copy of it
(rules_as_json()).

Three kinds of rule:
  - KEYS. A dict value whose key is sensitive is replaced outright. Keys are normalised first
    (camelCase → snake, case-folded, '-', '.' and spaces → '_', a leading http_ from WSGI META
    stripped), then matched exactly, by suffix (_token, _secret, _password, _key), or with every
    separator removed (PASS_WORD → password). An allow-list keeps known non-secrets readable.
  - TEXT. Inside every string: URL userinfo, sensitive query-parameter values, Authorization
    values, Bearer tokens, the auth cookies' values, key=value pairs for secret-named keys, JWTs,
    and long high-entropy runs. Each keeps its label (`?code=[Filtered]`) so a reader still knows
    what flow they are looking at.
  - SHAPE. Dicts, lists, tuples and JSON-in-a-string are walked to MAX_DEPTH. Deeper is
    "[truncated]", never "passed through because it was deep". Cycles become "[circular]".

scrub() never mutates its input and never raises: a scrubber that throws inside a log formatter
loses the log line it was protecting.
"""

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any
from uuid import UUID

REDACTED = "[Filtered]"
NOT_REDACTED = r"(?!" + REDACTED.replace("[", r"\[").replace("]", r"\]") + ")"
TRUNCATED = "[truncated]"
CIRCULAR = "[circular]"
UNREPRESENTABLE = "[unrepresentable]"

MAX_DEPTH = 10
MAX_ITEMS = 1000  # per container; the rest become one TRUNCATED marker
MAX_STRING = 100_000  # characters kept after scrubbing
JSON_PARSE_LIMIT = 64_000  # a string longer than this is not parsed as JSON

# --- Keys ---------------------------------------------------------------------------------------

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "old_password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "csrf",
        "x_csrf_token",
        "csrftoken",
        "sessionid",
        "api_key",
        "apikey",
        "x_api_key",
        "client_secret",
        "private_key",
        "otp",
        "totp",
        "mfa_code",
        "recovery_code",
        "mfa_token",
    }
)
SENSITIVE_SUFFIXES = ("_token", "_secret", "_password", "_key")
# Matches a suffix rule but is not a secret. Each line is a reviewed decision.
ALLOWED_KEYS = frozenset(
    {
        "cache_key",  # a cache lookup key
        "sort_key",  # an ordering field
        "public_key",  # public by definition
        "idempotency_key",  # a client-chosen request id
        "kid",  # a JWT key id names a key, it is not one
        "primary_key",  # a row id
        "foreign_key",  # a row id
    }
)


def normalise_key(key: object) -> str:
    """'X-API-Key' → 'x_api_key', 'apiKey' → 'api_key', 'PASS_WORD' → 'pass_word'."""
    text = key if isinstance(key, str) else str(key)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text).lower()
    text = re.sub(r"[\s\-.]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


# --- Text ---------------------------------------------------------------------------------------

QUERY_PARAMS = (
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "code",
    "state",
    "key",
    "api_key",
    "password",
    "secret",
    "client_secret",
    "signature",
    "sig",
    "reset_token",
    "invite_token",
)
TEXT_KEY_WORDS = (
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "id_token",
)

# High-entropy runs: base64/base64url-alphabet runs of at least this length, holding at least this
# many digits, upper- and lower-case letters. Random tokens pass easily; CamelCase identifiers and
# lower-case words joined by '-' or '_' do not. '/' is left out of the alphabet: URL paths stay
# legible.
HIGH_ENTROPY = {"min_length": 32, "min_digits": 2, "min_upper": 2, "min_lower": 2}


class ScrubRules:
    """The compiled rule set. `extra_keys` is how a module adds its own sensitive key names."""

    def __init__(self, *, cookie_prefix: str = "dbx", extra_keys: frozenset[str] = frozenset()):
        base = cookie_prefix.strip() or "dbx"
        self.cookie_names = tuple(f"{base}_{part}" for part in ("access", "refresh", "csrf"))
        cookie_keys = {normalise_key(n) for n in self.cookie_names}
        cookie_keys |= {normalise_key(f"__Host-{n}") for n in self.cookie_names}
        self.keys = frozenset(SENSITIVE_KEYS | cookie_keys | {normalise_key(k) for k in extra_keys})
        self._compact = frozenset(k.replace("_", "") for k in self.keys)
        self._allowed_compact = frozenset(k.replace("_", "") for k in ALLOWED_KEYS)

        cookies = "|".join(re.escape(n) for n in (*self.cookie_names, "sessionid", "csrftoken"))
        # After a kept label: never re-match a value that an earlier rule already replaced, or
        # "?token=x" becomes "?token=[Filtered]]" when the key=value rule runs over it.
        fresh = NOT_REDACTED
        # (name, pattern, flags). Every pattern has one capture group, the kept prefix, or none.
        # JavaScript-compatible syntax only: the frontend runs these same strings.
        self.text_patterns: tuple[tuple[str, str, str], ...] = (
            (
                "url_userinfo",
                r"(\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:)" + fresh + r"[^\s/@]+(?=@)",
                "i",
            ),
            (
                "query_param",
                r"([?&;](?:" + "|".join(QUERY_PARAMS) + r")=)" + fresh + r"[^&#\s\"'<>]+",
                "i",
            ),
            (
                "authorization",
                r"(\b(?:proxy-)?authorization[\"']?\s*[:=]\s*[\"']?"
                r"(?:(?:basic|bearer|digest|token)\s+)?)"
                + fresh
                # Without this the optional scheme backtracks on a re-scrub and the scheme word
                # itself becomes the "value": "Bearer [Filtered]" → "[Filtered] [Filtered]".
                + r"(?!(?:basic|bearer|digest|token)\s)[^\s\"',;]+",
                "i",
            ),
            ("bearer", r"(\bbearer\s+)[A-Za-z0-9\-._~+/]{16,}=*", "i"),
            ("cookie", r"((?:__Host-)?(?:" + cookies + r")=)" + fresh + r"[^;\s,\"']+", "i"),
            (
                "key_value",
                r"(\b[A-Za-z0-9_]*(?:"
                + "|".join(TEXT_KEY_WORDS)
                + r")[\"']?\s*[=:]\s*[\"']?)"
                + fresh
                + r"[^\s\"'&,;}\]]+",
                "i",
            ),
            ("jwt", r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*", ""),
            ("long_hex", r"\b[0-9a-fA-F]{48,}\b", ""),
        )
        self.high_entropy_pattern = (
            r"(?<![A-Za-z0-9_\-+])[A-Za-z0-9_\-+]{"
            + str(HIGH_ENTROPY["min_length"])
            + r",}={0,2}(?![A-Za-z0-9_\-+=])"
        )
        self._compiled = tuple(
            re.compile(pattern, re.IGNORECASE if "i" in flags else 0)
            for _, pattern, flags in self.text_patterns
        )
        self._high_entropy = re.compile(self.high_entropy_pattern)

    # -- keys --

    def is_sensitive_key(self, key: object) -> bool:
        name = normalise_key(key)
        candidates = {name, name.removeprefix("http_")}  # WSGI META: HTTP_AUTHORIZATION
        for candidate in candidates:
            compact = candidate.replace("_", "")
            if candidate in ALLOWED_KEYS or compact in self._allowed_compact:
                return False
        for candidate in candidates:
            if candidate in self.keys or candidate.replace("_", "") in self._compact:
                return True
            if candidate.endswith(SENSITIVE_SUFFIXES):
                return True
        return False

    # -- text --

    def scrub_text(self, text: str) -> str:
        for regex in self._compiled:
            text = regex.sub(_keep_prefix, text)
        text = self._high_entropy.sub(_high_entropy_replacement, text)
        return text

    def as_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "replacement": REDACTED,
            "truncated": TRUNCATED,
            "circular": CIRCULAR,
            "max_depth": MAX_DEPTH,
            "max_items": MAX_ITEMS,
            "max_string": MAX_STRING,
            "json_parse_limit": JSON_PARSE_LIMIT,
            "keys": sorted(self.keys),
            "key_suffixes": list(SENSITIVE_SUFFIXES),
            "allowed_keys": sorted(ALLOWED_KEYS),
            "strip_key_prefix": "http_",
            "query_params": list(QUERY_PARAMS),
            "cookie_names": list(self.cookie_names),
            "text_patterns": [
                {
                    "name": name,
                    "pattern": pattern,
                    "flags": flags,
                    # Group 1, when present, is kept in front of the replacement.
                    "keeps_prefix": compiled.groups > 0,
                }
                for (name, pattern, flags), compiled in zip(
                    self.text_patterns, self._compiled, strict=True
                )
            ],
            "high_entropy": {"pattern": self.high_entropy_pattern, **HIGH_ENTROPY},
        }


def _keep_prefix(match: re.Match) -> str:
    prefix = match.group(1) if match.re.groups else ""
    return (prefix or "") + REDACTED


def _high_entropy_replacement(match: re.Match) -> str:
    run = match.group(0)
    digits = sum(c.isdigit() for c in run)
    upper = sum(c.isupper() for c in run)
    lower = sum(c.islower() for c in run)
    if (
        digits >= HIGH_ENTROPY["min_digits"]
        and upper >= HIGH_ENTROPY["min_upper"]
        and lower >= HIGH_ENTROPY["min_lower"]
    ):
        return REDACTED
    return run


@lru_cache(maxsize=1)
def default_rules() -> ScrubRules:
    """The product's rules: the core set plus its auth cookie names, read from settings when they
    are configured. Built once; scrub() must work before settings exist, so this never raises."""
    prefix = "dbx"
    try:
        from django.conf import settings

        if settings.configured:
            prefix = getattr(settings, "AUTH_COOKIE_PREFIX", prefix) or prefix
    except Exception:  # noqa: BLE001 — no settings yet is normal at import time
        pass
    return ScrubRules(cookie_prefix=prefix)


def rules_as_json() -> dict[str, Any]:
    """The rule set as JSON-able data, for the generated frontend copy (§ 3)."""
    return default_rules().as_json()


# --- The walk -----------------------------------------------------------------------------------

_PLAIN = (bool, int, float, Decimal, datetime, date, time, timedelta, UUID, type(None))


def scrub(value: Any, rules: ScrubRules | None = None) -> Any:
    """A scrubbed copy of `value`. Never mutates it, never raises."""
    try:
        return _scrub(value, rules or default_rules(), 0, set())
    except Exception:  # noqa: BLE001 — the last line of defence must not be the thing that fails
        return REDACTED


def _scrub(value: Any, rules: ScrubRules, depth: int, path: set[int]) -> Any:
    if isinstance(value, _PLAIN):
        return value
    if depth > MAX_DEPTH:
        return TRUNCATED
    if isinstance(value, str):
        return _scrub_string(value, rules, depth, path)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value[: MAX_STRING * 4])
        return _scrub_string(raw.decode("utf-8", errors="replace"), rules, depth, path)

    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set, frozenset)):
        marker = id(value)
        if marker in path:
            return CIRCULAR
        path.add(marker)
        try:
            if isinstance(value, Mapping):
                return _scrub_mapping(value, rules, depth, path)
            return _scrub_sequence(value, rules, depth, path)
        finally:
            path.discard(marker)

    # Anything else would reach a log through str(): scrub what str() would have shown.
    try:
        return rules.scrub_text(str(value))[:MAX_STRING]
    except Exception:  # noqa: BLE001 — a __str__ that raises
        return UNREPRESENTABLE


def _scrub_mapping(value: Mapping, rules: ScrubRules, depth: int, path: set[int]) -> dict:
    out: dict = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= MAX_ITEMS:
            out[TRUNCATED] = len(value) - MAX_ITEMS
            break
        out[key] = REDACTED if rules.is_sensitive_key(key) else _scrub(item, rules, depth + 1, path)
    return out


def _scrub_sequence(value, rules: ScrubRules, depth: int, path: set[int]):
    items = []
    for index, item in enumerate(value):
        if index >= MAX_ITEMS:
            items.append(TRUNCATED)
            break
        items.append(_scrub(item, rules, depth + 1, path))
    return tuple(items) if isinstance(value, tuple) else items


def _scrub_string(text: str, rules: ScrubRules, depth: int, path: set[int]) -> str:
    stripped = text.lstrip()
    if stripped[:1] in ("{", "[") and len(text) <= JSON_PARSE_LIMIT:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            cleaned = _scrub(parsed, rules, depth + 1, path)
            return json.dumps(cleaned, ensure_ascii=False, default=str)
    # Scrub the whole string first, then cut: cutting first could leave half a secret that no
    # longer matches any pattern.
    cleaned = rules.scrub_text(text)
    if len(cleaned) > MAX_STRING:
        return cleaned[:MAX_STRING] + TRUNCATED
    return cleaned
