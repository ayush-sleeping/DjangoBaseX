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

from core.identity import SHIPPED_COOKIE_PREFIX

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

# High-entropy runs (TECH_DEBT DB-51). A candidate is a run of at least min_length characters from
# the base64/base64url alphabet (A-Z a-z 0-9 _ - + /, optional '=' padding). It is a secret unless
# it reads like words. Every threshold below was measured, not guessed, against seeded random
# tokens and a corpus of real identifier and string runs (tests/test_scrub_entropy.py):
#   1. Pure hex of 32+ characters holding a digit and a letter is a secret (token_hex, uuid4().hex,
#      digests). Exception: a 40-hex run labelled commit/sha/rev(ision) stays: a git SHA.
#   2. Hyphenated UUIDs are object ids people need to read; they are masked out before judging.
#   3. A mixed-case run is judged by its word share: the share of its letters and digits that sit in
#      English-like word segments (CamelCase/snake split; see _is_word). Real identifiers score
#      near 0.9. Random base64 of 28+ characters never exceeded 0.571 in 2.4 million tokens; 20-27
#      characters (22- and 24-character tokens) reached 0.783, hence the two thresholds.
#   4. A single-case run (snake_case, kebab-case, CONSTANTS, paths) is a secret only when digits sit
#      between letters AND 30%+ of its letter pairs are un-English: the ~1e-5 of random tokens with
#      no upper- or no lower-case letter at all.
# The old rule (32+ characters, 2 digits, 2 upper, 2 lower, '/' excluded) missed every 22-character
# token, every lowercase hex token, most standard base64, and 0.5% of token_urlsafe(32).
HIGH_ENTROPY = {
    "min_length": 20,
    "min_hex_length": 32,
    "min_distinct": 8,
    "guaranteed_from": 28,
    "max_word_share_short": 0.65,
    "max_word_share_mid": 0.76,
    "long_from": 40,
    "max_word_share_long": 0.62,
    "single_case_min_digits": 2,
    "separator_free_min_rare_share": 0.15,
    "min_word_segment": 4,
    "max_segment_rare_share": 0.25,
    "min_segment_vowel_share": 0.2,
    "max_consonant_run": 4,
    "single_case_min_rare_share": 0.3,
}
# Band 2's context rule: a 20-27 character run (mixed case or holding digits) right after one of
# these words is redacted whatever its word share. "reset token abc…", "api_key=…", "password is …".
SECRET_CONTEXT_WORDS = (
    "api_key|api-key|apikey|token|secret|key|password|passwd|pwd|authorization|auth|bearer|"
    "signature|sig|session|cookie|credential|otp|code|csrf|jwt"
)
_SECRET_CONTEXT = re.compile(
    r"(?<![a-z])(?:" + SECRET_CONTEXT_WORDS + r")s?(?:\s+is\s+|\s*[:=]\s*|\s+|\s*\(\s*)['\"]?$",
    re.IGNORECASE,
)
CONTEXT_WINDOW = 40
# Correlation ids are not secrets, and redacting them breaks every log join. A value under one of
# these keys passes through verbatim, but only when it is shaped like an id (hex or UUID): anything
# else under the key is scrubbed as usual, so the exemption cannot carry a secret.
CORRELATION_KEYS = frozenset(
    {"request_id", "x_request_id", "trace_id", "span_id", "correlation_id", "task_id", "run_id"}
)
_ID_SHAPED = re.compile(r"[0-9a-fA-F-]{8,64}")
# Short pieces real identifiers are built from (CONFIGURATION/API names, Django, DRF, Celery): they
# count as words even though they are under min_word_segment letters.
SHORT_WORDS = frozenset(
    (
        "id ids db url uri api app max min get set add raw key sql sha md5 src dst ttl utc dir doc "
        "env err log msg obj ref req res row tag tmp txt uid val var xml csv pdf png svg tls ssl "
        "jwt web job run new old end all any bit buf cmd col ctx def del dev dns fmt fn gid hex "
        "img int str len lib net num opt out pid pk qs rpc sig sub sum sys tab tz ui ux vm "
        "is on in of "
        "to by as at or and not for has can use via per mix tpl gis geo css html http https json "
        "yaml rest form auth user list view test mfa csrf otp ip "
    ).split()
)
# The 310 letter pairs that make up 98% of all letter pairs in English words (macOS
# /usr/share/dict/words, 235k words). A pair outside this set is "rare". Fixed here, not read from
# the OS at runtime, so every process and the frontend judge identically.
COMMON_BIGRAMS = frozenset(
    (
        "ab ac ad ae af ag ah ai ak al am an ap ar as at au av aw ax ay az ba bb be bi bl bo br "
        "bs bu ca cc ce ch ci ck cl co cr ct cu cy da dd de di dl dn do dr du dy ea eb ec ed ee "
        "ef eg eh ei el em en eo ep er es et eu ev ew ex ey fa fe ff fi fl fo fr ft fu ga ge gg "
        "gh gi gl gn go gr gu gy ha he hi hl hn ho hr ht hu hy ia ib ic id ie if ig ik il im in "
        "io ip ir is it iu iv iz ja je ju ka ke ki kl la lc ld le li ll lm ln lo lp ls lt lu lv "
        "ly ma mb me mi mm mn mo mp mu my na nb nc nd ne nf ng nh ni nk nl nm nn no np nr ns nt "
        "nu nv nw ny oa ob oc od oe of og oh oi ok ol om on oo op or os ot ou ov ow ox pa pe ph "
        "pi pl po pp pr ps pt pu py qu ra rb rc rd re rf rg rh ri rk rl rm rn ro rp rr rs rt ru "
        "rv rw ry sa sc se sh si sk sl sm sn so sp sq ss st su sw sy ta tc te th ti tl to tr ts "
        "tt tu tw ty ua ub uc ud ue ug ui ul um un uo up ur us ut va ve vi vo wa we wh wi wo xa "
        "xi xt ya yc yd ye yg yi yl ym yn yo yp yr ys yt za ze zi zo"
    ).split()
)
_WORD_SEGMENT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+|[^A-Za-z0-9]")
_HEX_RUN = re.compile(r"[0-9a-f]+|[0-9A-F]+")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_GIT_LABEL = re.compile(r"(?:commit|sha1?|rev|revision)[\s:=#]*$", re.IGNORECASE)
_DIGIT_ISLAND = re.compile(r"[A-Za-z][0-9]+[A-Za-z]")
_CONSONANT_RUN = re.compile(
    r"[b-df-hj-np-tv-xz]{" + str(HIGH_ENTROPY["max_consonant_run"] + 1) + ",}", re.IGNORECASE
)
_VOWELS = frozenset("aeiouyAEIOUY")
_SEPARATOR = re.compile(r"[_\-/+]")


class ScrubRules:
    """The compiled rule set. `extra_keys` is how a module adds its own sensitive key names."""

    def __init__(
        self,
        *,
        cookie_prefix: str = SHIPPED_COOKIE_PREFIX,
        extra_keys: frozenset[str] = frozenset(),
    ):
        base = cookie_prefix.strip() or SHIPPED_COOKIE_PREFIX
        # The auth cookies (users.cookies), then the admin's session and CSRF (settings).
        parts = ("access", "refresh", "csrf", "sessionid", "csrftoken")
        self.cookie_names = tuple(f"{base}_{part}" for part in parts)
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
        # One character class, bounded by lookarounds: linear, no nested quantifiers to backtrack.
        self.high_entropy_pattern = (
            r"(?<![A-Za-z0-9_\-+/])[A-Za-z0-9_\-+/]{"
            + str(HIGH_ENTROPY["min_length"])
            + r",}={0,2}(?![A-Za-z0-9_\-+/=])"
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
            "high_entropy": {
                "pattern": self.high_entropy_pattern,
                **HIGH_ENTROPY,
                "common_bigrams": sorted(COMMON_BIGRAMS),
                "short_words": sorted(SHORT_WORDS),
            },
        }


def _keep_prefix(match: re.Match) -> str:
    prefix = match.group(1) if match.re.groups else ""
    return (prefix or "") + REDACTED


def _high_entropy_replacement(match: re.Match) -> str:
    run = match.group(0)
    if (
        _HEX_RUN.fullmatch(run)
        and len(run) == 40
        and _GIT_LABEL.search(match.string[max(0, match.start() - 12) : match.start()])
    ):
        return run  # a git commit SHA, labelled as one
    if looks_secret(run):
        return REDACTED
    if _after_secret_word(match) and (
        any(c.isdigit() for c in run) or (run.lower() != run and run.upper() != run)
    ):
        return REDACTED  # band 2: context catches what word share cannot judge alone
    return run


def _after_secret_word(match: re.Match) -> bool:
    window = match.string[max(0, match.start() - CONTEXT_WINDOW) : match.start()]
    return bool(_SECRET_CONTEXT.search(window))


def looks_secret(run: str) -> bool:
    """Does a base64/base64url/hex-alphabet run look like a credential rather than words?"""
    core = run.rstrip("=")
    if len(set(core)) < HIGH_ENTROPY["min_distinct"]:
        return False  # "xxxx…", "----…": filler, never a credential
    if len(core) >= HIGH_ENTROPY["min_hex_length"] and _HEX_RUN.fullmatch(core):
        return any(c.isdigit() for c in core) and any(c.isalpha() for c in core)
    for chunk in _UUID.split(core):  # hyphenated UUIDs are readable ids, not secrets
        if len(chunk) < HIGH_ENTROPY["min_length"]:
            continue
        if any(c.isupper() for c in chunk) and any(c.islower() for c in chunk):
            if _word_share(chunk) < _word_share_limit(len(chunk)):
                return True
        elif (
            len(chunk) >= HIGH_ENTROPY["guaranteed_from"]
            and not _SEPARATOR.search(chunk)
            and (
                sum(c.isdigit() for c in chunk) >= HIGH_ENTROPY["single_case_min_digits"]
                or _rare_share(chunk) >= HIGH_ENTROPY["separator_free_min_rare_share"]
            )
        ):
            return True  # base32 secrets (TOTP): one case, digits, no word separators
        elif _DIGIT_ISLAND.search(chunk) and (
            _rare_share(chunk) >= HIGH_ENTROPY["single_case_min_rare_share"]
        ):
            return True
    return False


def _word_share_limit(length: int) -> float:
    """Below this word share a mixed-case run is a secret. Measured per band: random tokens
    peaked at 0.783 (20-27 chars), 0.720 (28-39) and 0.550 (40+)."""
    if length >= HIGH_ENTROPY["long_from"]:
        return HIGH_ENTROPY["max_word_share_long"]
    if length >= HIGH_ENTROPY["guaranteed_from"]:
        return HIGH_ENTROPY["max_word_share_mid"]
    return HIGH_ENTROPY["max_word_share_short"]


def _rare_share(text: str) -> float:
    """The share of adjacent letter pairs (case-folded) that are not common English pairs."""
    pairs = [
        (a + b).lower()
        for segment in re.findall(r"[A-Za-z]+", text)
        for a, b in zip(segment, segment[1:], strict=False)
    ]
    if not pairs:
        return 1.0
    return sum(pair not in COMMON_BIGRAMS for pair in pairs) / len(pairs)


def _is_word(segment: str) -> bool:
    """A CamelCase/snake segment that reads as a word: a known short identifier piece, or 4+
    letters with English letter pairs, some vowels and no long consonant cluster."""
    if not segment.isalpha():
        return False
    if segment.lower() in SHORT_WORDS:
        return True
    return (
        len(segment) >= HIGH_ENTROPY["min_word_segment"]
        and _rare_share(segment) <= HIGH_ENTROPY["max_segment_rare_share"]
        and not _CONSONANT_RUN.search(segment)
        and sum(c in _VOWELS for c in segment) / len(segment)
        >= HIGH_ENTROPY["min_segment_vowel_share"]
    )


def _word_share(text: str) -> float:
    """The share of letters and digits inside word segments. Separators are word boundaries in an
    identifier, not content, so they are left out of the denominator."""
    alnum = sum(c.isalnum() for c in text)
    if not alnum:
        return 0.0
    return sum(len(seg) for seg in _WORD_SEGMENT.findall(text) if _is_word(seg)) / alnum


@lru_cache(maxsize=1)
def default_rules() -> ScrubRules:
    """The product's rules: the core set plus its auth cookie names, read from settings when they
    are configured. Built once; scrub() must work before settings exist, so this never raises."""
    prefix = SHIPPED_COOKIE_PREFIX
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
        if rules.is_sensitive_key(key):
            out[key] = REDACTED
        elif _is_correlation_id(key, item):
            out[key] = item
        else:
            out[key] = _scrub(item, rules, depth + 1, path)
    return out


def _is_correlation_id(key: object, item: object) -> bool:
    name = normalise_key(key).removeprefix("http_")
    return name in CORRELATION_KEYS and isinstance(item, str) and bool(_ID_SHAPED.fullmatch(item))


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
