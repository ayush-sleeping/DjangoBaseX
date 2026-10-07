# Observability

**How a running DjangoBaseX product tells you what it is doing, what went wrong, and — just as
important — what it is *not* measuring: request correlation, structured logs, one scrubber, error
tracking, health, data-plane checks, metrics, self-watching alerts, the System Health page, the
"zero is not a fact" state model, and the doctors.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

---

## Scope — read first

**Owns:** the request id and its propagation (Django, Celery, Next) · the `LOGGING` configuration,
log fields and log hygiene · the single scrubber and its exported deny-list · Sentry configuration ·
the built-in error tracker · the three health rungs and the `health` registry · data-plane
self-checks · the metrics registry and exporter · the Prometheus/Alertmanager rule pack and its
config tests · the System Health admin page · the `Figure` state model (`live|quiet|never|off|untracked`) ·
the `manage.py doctor` umbrella, its registry and its backlog ledgers.

**Does not own:**

| Topic | Owner |
|---|---|
| Boot refusal, `APP_ENV`, `is_production_like()`, the settings registry, guard modes | [`CONFIGURATION.md`](CONFIGURATION.md) — this file only states which observability settings the boot audit must refuse |
| The error envelope shape and the error-code catalogue | [`API_PLATFORM.md`](API_PLATFORM.md) — this file only requires a `request_id` in it (§ 1, § 16) |
| Job registry, run monitor, queue invariants, schedule monitor | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) — this file *consumes* their health states |
| Notification routing, the ops-alert dispatcher, incidents, quiet hours, digests | [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md) — this file owns only the Prometheus rule pack that feeds it |
| Activity/audit log, retention engine | [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) — this file registers retention policies and a retention doctor |
| Error boundaries, load-state contract, `StatTile` rendering | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) — this file owns the data contract they render |
| Deploy verification, container log drivers, proxy log format, backups freshness metric source | [`OPERATIONS.md`](OPERATIONS.md) |
| Registry mechanics (registration shape, freezing, discovery) | [`EXTENSIBILITY.md`](EXTENSIBILITY.md) — every registry named here must appear in its catalogue |
| Credentials never logged, auth-specific redaction | [`SECURITY.md`](SECURITY.md), [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) |

---

## 0. The rules in one screen

1. **Every request, task and command has exactly one request id**, set before anything else runs and cleared only after the response is fully sent — [§ 1](#1-the-request-id--tier-1--core)
2. **An inbound `X-Request-ID` is honoured only from a trusted proxy, and only if it matches `^[A-Za-z0-9._-]{1,64}$`.** A newline forges log lines — [§ 1](#1-the-request-id--tier-1--core)
3. **The id is echoed in the response header, in every error body, in Celery headers and in Next's server-side fetches** — [§ 1](#1-the-request-id--tier-1--core)
4. **Production logs are JSON, one record per line, and only allow-listed fields leave the process.** The boot audit refuses `LOG_FORMAT=console` in production — [§ 2](#2-structured-logging--tier-1--core)
5. **Request and response bodies are never logged — not at DEBUG, not "temporarily".** A canary test proves it on the success, validation and 500 paths — [§ 2](#2-structured-logging--tier-1--core)
6. **Validation failures are logged as field → error *codes*, never messages or values** — [§ 2](#2-structured-logging--tier-1--core)
7. **One traceback per 500.** Exactly one `ERROR` record carries `exc_info` — [§ 2](#2-structured-logging--tier-1--core)
8. **There is one scrubber.** Logs, Sentry (backend and all three Next runtimes) and the built-in tracker all call it; the frontend's copy is *generated* from the backend's rules — [§ 3](#3-one-scrubber--tier-1--core)
9. **`send_default_pii=False`, no frame locals, no request bodies, 404s dropped, health never traced** — [§ 4](#4-sentry--tier-2--core)
10. **One `APP_VERSION` names a release everywhere** — backend, frontend, Sentry, the built-in tracker, the metrics `build_info` — [§ 4](#4-sentry--tier-2--core)
11. **An error fingerprint excludes the message**, and only a *resolved* group reopens — [§ 5](#5-the-built-in-error-tracker--tier-2--core)
12. **Liveness does no I/O. Readiness checks the database and the cache — nothing else — with timeouts and fixed-token errors. Detail lives behind a permission** — [§ 6](#6-health--three-rungs--tier-1--core)
13. **A probe never raises, and only a core dependency can make the install `down`** — [§ 6](#6-health--three-rungs--tier-1--core)
14. **Configuration that lives in rows has no schema to fail loudly — so the rows the product cannot live without are checked** at boot, in health and as a metric — [§ 7](#7-data-plane-self-checks--tier-2--core)
15. **Every metric label set is closed and pre-initialised at zero.** "No data" must never look like "healthy" — [§ 8](#8-metrics--tier-2--core)
16. **A `/metrics` callable never raises.** One exception blanks every series and every alert with it — [§ 8](#8-metrics--tier-2--core)
17. **Alerting watches itself** — a dead-man's switch, "never attempted", `absent()` for every target — and its config is tested — [§ 9](#9-alerting-that-watches-itself--tier-2--core)
18. **Zero is not a fact.** Every figure carries its mechanism's state; "not measured" is never rendered as `0` — [§ 11](#11-zero-is-not-a-fact--the-figure-state-model--tier-2--core)
19. **A doctor calls the real enforcement code, never a second model of it**, and never prints "healthy" over a non-empty backlog — [§ 12](#12-doctors--tier-1--core)
20. **A check that fails forty times on its first run gets switched off.** New checks ship with a shrink-only ledger of what already fails — [§ 13](#13-check-hygiene--the-forty-failures-rule--process)

---

## 1. The request id — **Tier 1 · Core**

**What.** A `core.observability.request_id.RequestIdMiddleware`, **first** in `MIDDLEWARE`, that
decides one id per request, stores it in a `ContextVar`, echoes it as `X-Request-ID`, and makes it
available to every log record, every error body, every Celery task the request publishes, and every
outbound call the platform makes.

**Why.** Without it, a user's "it broke at 14:02" is a grep through interleaved lines from every
worker. With it, a support conversation starts with a reference string and ends at the exact log
lines, the exact Sentry event and the exact background task that followed.

A real incident, twice over: the id was reset in a `finally` block. The first time, the reset ran
**before** the error handler built the 500 body, so every 500 told the user their reference was `-`.
The second time, every access-log line read `[-]`, because the access line is written after the
application returns. Both are the obvious implementation. Both were shipped.

**Rules.**

- **First act, before anything can log.** The middleware sits above `CorsMiddleware` (so preflight
  responses carry an id too) and above everything else. It sets the var before calling
  `get_response`, and it does **not** reset it on the way out.
- **Reset only after the response is fully sent** — in a `request_finished` receiver, which Django
  fires from `response.close()`, i.e. after a streamed body has been iterated. Under WSGI a thread's
  context outlives the request, so without the reset the next request's pre-middleware logging (and
  anything the server logs between requests) inherits a stale id. Under ASGI each request runs in its
  own context and the reset is harmless.
- **Validate before trusting.** Accept an inbound id only if it matches `^[A-Za-z0-9._-]{1,64}$`.
  Anything else — including a value containing `\n`, which in a text log is a forged log line — is
  discarded and a fresh id generated.
- **Trust inbound ids only from a trusted proxy.** When `TRUSTED_PROXY_COUNT > 0` (the same setting
  `core/http.py::client_ip()` uses, [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.3), the edge proxy
  is required to **set** `X-Request-ID` itself ([`OPERATIONS.md`](OPERATIONS.md) § 14), so the
  header can be believed. When the app is not behind a proxy, a caller-supplied id is recorded
  separately as `client_request_id` (still validated) and never becomes the primary id — a client
  must not be able to make its requests collide with someone else's in the logs.
- **Generate** ids as 32 lowercase hex characters (`uuid4().hex`). Same shape as the edge proxy's
  own `$request_id`, so an operator cannot tell by eye which layer minted it, and does not need to.
- **Echo it everywhere a human might copy it from:** the `X-Request-ID` response header; the
  `request_id` field of **every** error envelope, 4xx included (the envelope is owned by
  [`API_PLATFORM.md`](API_PLATFORM.md) — see § 16); the frontend's error state, next to Next's
  `error.digest` for server-component failures.
- **Access logs read the id from the response header, not the var.** Gunicorn's access line is
  written after the app returns; `%({x-request-id}o)s` in `access_log_format` reads the header the
  middleware set, which is the only reliable source at that moment ([`OPERATIONS.md`](OPERATIONS.md) § 7).
- **Celery.** A `before_task_publish` receiver copies the current id into the task headers as
  `request_id`; a `task_prerun` receiver sets the var from `task.request.request_id` and
  `task_postrun` resets it. A task published with no request in scope (a beat schedule, a shell)
  gets a fresh id prefixed `job-`, so a task chain started by beat is still one traceable story.
- **Management commands** get an id prefixed `cmd-` from the core `BaseCommand` wrapper, so a
  `migrate` or `doctor` run is greppable as a unit.
- **Outbound HTTP.** The SSRF-safe client ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md))
  sends the id as `X-Request-ID` to internal services only — never to third parties, where it is a
  correlation handle nobody asked us to give away.
- **Next.js.** `src/proxy.ts` (Next 16's renamed middleware) does not mint ids — the edge proxy has
  already set one on every request. Server-side fetches in `src/lib/api.ts` read it with
  `(await headers()).get("x-request-id")` (async in Next 16) and forward it to `INTERNAL_API_URL`,
  so a server component's API call and the page request share one id. `instrumentation.ts`'s
  `onRequestError` logs `digest` **and** `request_id` together — the only place the two are joined.
- **User and tenant ids are set where they become known, not in middleware.** DRF authenticates
  inside the view, so middleware only ever sees `AnonymousUser`. `CookieJWTAuthentication`
  sets `USER_ID` on success; the tenancy resolver ([`REUSABLE_MODULES.md`](REUSABLE_MODULES.md))
  sets `TENANT_ID`. Both reset in the same `request_finished` receiver.

**Django + Next shape.**

```python
# core/observability/request_id.py
REQUEST_ID = ContextVar("request_id", default="-")
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid, client_rid = resolve_request_id(request)   # validate + trust decision, § 1
        REQUEST_ID.set(rid)                              # FIRST act. No token kept: not reset here
        request.request_id, request.client_request_id = rid, client_rid
        response = self.get_response(request)
        response["X-Request-ID"] = rid
        return response

@receiver(request_finished)          # fires after the body — streamed or not — is sent
def _clear_context(**_): REQUEST_ID.set("-"); USER_ID.set(None); TENANT_ID.set(None)
```

**Enforced by.**

- `tests/observability/test_request_id.py`:
  - `test_500_body_and_header_carry_the_same_id` — a view that raises; the envelope's `request_id`
    equals the header and is not `-`. **Fails against the reset-in-`finally` implementation** —
    write it first, watch it fail, then fix.
  - `test_log_emitted_while_streaming_carries_the_id` — a `StreamingHttpResponse` whose generator
    logs; the captured record carries the id.
  - `test_newline_in_inbound_id_is_discarded` and `test_65_char_id_is_discarded`.
  - `test_inbound_id_ignored_without_trusted_proxy` — `TRUSTED_PROXY_COUNT=0`; the caller's value
    lands in `client_request_id`, not `request_id`.
  - `test_celery_task_inherits_the_publishing_request_id` — `CELERY_TASK_ALWAYS_EAGER` is **not**
    enough (eager tasks skip publish signals); run with a real in-memory broker.
- A system check `dbx.E010`: `RequestIdMiddleware` is `MIDDLEWARE[0]`.

**Configurable, not hard-coded.** `REQUEST_ID_HEADER` (default `X-Request-ID`) ·
`REQUEST_ID_TRUST` (`proxy` default — trust iff `TRUSTED_PROXY_COUNT > 0`; `never`; `always`,
refused by the boot audit outside development) · the id pattern and length are constants, not
settings — loosening them is a security change.

---

## 2. Structured logging — **Tier 1 · Core**

**What.** One `LOGGING` dict, built by `core.observability.logging.build_logging(env)` and
assigned in `config/settings.py`; a context filter that stamps every record with `request_id`,
`user_id`, `tenant_id` and `plugin`; a JSON formatter that emits **only allow-listed fields**; and a
set of hygiene rules for what may be logged at all. Closes `TECH_DEBT` **DB-9**.

**Why.** A 500 today goes to stdout as text and is lost. Beyond that, the two failure modes of
logging are equal and opposite: too little (no correlation, no structure, nothing searchable) and too
much (passwords and tokens in log storage, which is usually the least-protected data store an
organisation runs). A real incident: a validation handler logged the raw request body "for
debugging", and passwords, one-time codes and government identifiers sat in logs and in the error
tracker for months. Another: permission-granted lines were half of all log volume, and the noise hid
a live stock-level bug for weeks.

**Rules.**

- **JSON in production, enforced.** `LOG_FORMAT=json|console`. The boot audit
  ([`CONFIGURATION.md`](CONFIGURATION.md)) refuses `console` when `is_production_like()`. A console
  format in production is a log that no aggregator can query and that a newline in a message can
  forge.
- **Allow-listed fields only.** The formatter emits a fixed core set (`ts`, `level`, `logger`, `msg`,
  `request_id`, `client_request_id`, `user_id`, `tenant_id`, `plugin`, `event`, `duration_ms`,
  `status`, `method`, `route`, `exc_type`, `exc`) plus fields a module has **registered**
  (`registry.log_fields.register("billing", {"invoice_id", "provider"})`). An `extra=` key nobody
  registered is dropped and counted (`app_log_fields_dropped_total{logger}`) — so a careless
  `logger.info("x", extra={"request": request.data})` cannot leak, and the drop is visible.
- **Scrub last.** Every emitted dict passes through the scrubber (§ 3) after assembly — including
  `msg`, because an f-string can interpolate a token as easily as `extra` can.
- **Filters go on handlers, not loggers.** A Python logger's own filters apply only to records
  logged *on that logger*, not to records propagated up from children. A context filter attached to
  the root logger silently misses `django.request`, `celery.*` and every plugin logger. Attach it to
  every handler.
- **`route` is the URL name, never the path.** `/api/users/41/` and `/api/users/87/` are one route;
  a path field is also a PII field (it can contain an email in a lookup).
- **Never log bodies.** Not request bodies, not response bodies, not "the first 200 bytes". Not at
  DEBUG. The only exception is none.
- **Validation failures log codes.** The DRF exception handler logs a `ValidationError` at `INFO`
  as `{"fields": {"email": ["invalid"], "role": ["does_not_exist"]}}` using `exc.get_codes()`.
  **Not** the messages: DRF's own messages echo input (`'"x" is not a valid choice.'`), so a
  message is a value by another name.
- **One traceback per 500.** The core exception handler logs the unhandled exception once, at
  `ERROR`, with `exc_info`, under logger `core.errors`. Django's `django.request` logger then emits
  its own traceback-less "Internal Server Error" line for the same response — a filter drops it when
  the request is already marked as logged, and demotes `django.request` 4xx lines to `DEBUG`
  (they are the access log's job). Result: exactly one record per failure, and it is the one with
  the stack.
- **Access logs at DEBUG.** Per-request "granted"/"served" lines belong in the proxy's access log
  ([`OPERATIONS.md`](OPERATIONS.md) § 14), which is structured and cheap. Denials stay at `WARNING`
  — a denial is a fact about security; a grant is a fact about traffic.
- **Security events are not noise.** `DisallowedHost`, CSRF failures, lockouts and
  `authz.superuser_bypass` go to a `security` logger at `WARNING` with their own fields. They are
  rate-limited at the handler (one line per key per minute plus a count), because a scanner can
  produce ten thousand of them.
- **Celery uses the same config.** Set `worker_hijack_root_logger = False` and connect Celery's
  `setup_logging` signal to a no-op so Celery does not replace Django's `LOGGING`. A worker that
  logs in a different format from the web process is how a background failure becomes unsearchable.
- **Library loggers pinned.** `django.db.backends` at `WARNING` (DEBUG logs every SQL statement
  with parameters — which include password hashes and tokens), `urllib3` / `botocore` at `WARNING`.
- **Logs go to stdout; the container runtime ships them.** No file handlers in the app — rotating
  file handlers shared by several processes lose and interleave lines. The log driver must
  **survive container recreation**: the default `json-file` log is deleted with the container, so
  every deploy wipes the history of the release it replaced. `journald` (with host caps) or a
  shipper is required in production; [`OPERATIONS.md`](OPERATIONS.md) § 15 and the policy test in
  § 16 there enforce it.

**Django + Next shape.**

```python
# core/observability/logging.py
class ContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = REQUEST_ID.get()
        record.user_id, record.tenant_id = USER_ID.get(), TENANT_ID.get()
        record.plugin = plugin_for_logger(record.name)       # registry lookup, memoised
        return True

class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {"ts": iso_utc(record.created), "level": record.levelname,
               "logger": record.name, "msg": safe_message(record), **context_fields(record)}
        out |= {k: v for k, v in vars(record).items() if k in allowed_extra_fields()}
        if record.exc_info:
            out["exc_type"], out["exc"] = format_exc_parts(record.exc_info)
        return json.dumps(scrub(out), default=str, ensure_ascii=False)
```

`safe_message()` catches the `TypeError` a mismatched `%s` raises — a logging call must never be
the thing that crashes a request. JSON-encoding escapes `\n`, which is the structural defence
against log forging; the request-id validation in § 1 is the second.

Frontend: server-side code logs through `src/lib/log.ts` — `console.log(JSON.stringify(scrub(...)))`
in production, the same field names as the backend, `request_id` included. An optional
`POST /api/client-logs/` intake for browser errors is **Tier 3** (rate-limited, schema-validated,
batched, and it must not use the authenticated transport — a 401 redirect while logging the 401 is a
loop).

**Enforced by.**

- `tests/observability/test_no_bodies_in_logs.py` — **the canary test.** Sends
  `password="CANARY-<uuid>"` through the login success path, the validation-failure path and a
  forced-500 path, with every handler, the Sentry transport (in-memory) and the built-in tracker
  captured. Asserts the canary appears **nowhere**. Includes a **positive control**: a test-only view
  that deliberately logs its body, asserting the detector *does* find the canary — otherwise the
  test passes because the capture is broken.
- `test_one_traceback_per_500` — exactly one captured record with `exc_info` for one failure.
- `test_validation_logged_as_codes` — a `ChoiceField` failure; the logged record contains the code
  and not the submitted value.
- `test_unregistered_extra_is_dropped_and_counted`.
- `test_context_filter_on_every_handler` — walks `LOGGING["handlers"]`.
- Boot audit (`CONFIGURATION.md`): `LOG_FORMAT=console` refused when production-like; a CI step
  imports settings with `APP_ENV=production` and a console format and **fails if it imports**.

**Configurable, not hard-coded.** `LOG_FORMAT` · `LOG_LEVEL` · `LOG_LEVELS` (per-logger overrides,
`django.db.backends=WARNING,…`) · `LOG_SECURITY_RATE_LIMIT` (per key per minute) · the core field
allow-list is a constant; module fields are registry entries.

---

## 3. One scrubber — **Tier 1 · Core**

**What.** `core/observability/scrub.py` — one function, `scrub(value)`, and one rule set
(`ScrubRules`), used by the log formatter (§ 2), Sentry's `before_send`/`before_send_transaction`/
`before_breadcrumb` (§ 4), the built-in error tracker (§ 5) and the activity log's diff masking
([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)). The rules are exported as JSON and **generated** into
the frontend, where the Next scrubber for all three runtimes consumes them.

**Why.** Two scrubbers disagree. A real incident: the browser's error-tracker scrubber was
case-sensitive, never scrubbed the request URL or the POST body, and the server and edge runtimes
had no scrubber at all — "so server-rendered errors leaked everything". Another: key matching was a
substring match on `token`, which redacted `token_count` and missed `Authorization`. `SECURITY.md`'s
"redact at the formatter" is right but incomplete: the formatter is one of four exits.

**Rules.**

- **Keys — exact names, case-insensitive, `-` normalised to `_`:** `password`, `new_password`,
  `old_password`, `passwd`, `secret`, `token`, `access_token`, `refresh_token`, `id_token`,
  `authorization`, `proxy_authorization`, `cookie`, `set_cookie`, `x_csrf_token`, `csrftoken`,
  `sessionid`, `api_key`, `apikey`, `x_api_key`, `client_secret`, `private_key`, `otp`, `mfa_code`,
  `recovery_code` — **plus the product's own cookie names, read from settings** (the auth cookies
  derive from a slug, [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12, so a literal list would miss
  them in every product).
- **Keys — suffix rules:** anything ending `_token`, `_secret`, `_password`, `_key`. An explicit
  **allow** set keeps obvious non-secrets readable (`cache_key`, `sort_key`, `public_key`,
  `idempotency_key`, `kid`) — each addition is a reviewed line with a reason.
- **Values in free text:** `Bearer <token>` anywhere in a string; anything JWT-shaped
  (`eyJ…​.…​.…`); URL userinfo (`scheme://user:pass@host` → `scheme://user:[redacted]@host`);
  and the **values** of sensitive query parameters in any URL-looking substring — `token`,
  `access_token`, `refresh_token`, `id_token`, `code`, `state`, `key`, `api_key`, `password`,
  `secret`, `client_secret`, `signature`, `sig`, `reset_token`, `invite_token`. The parameter name
  is kept (`?code=[redacted]`) so the reader still knows what flow they are looking at.
- **Headers:** `authorization`, `proxy-authorization`, `cookie`, `set-cookie`, `x-csrf-token`,
  `x-api-key`, and any header matching the key rules.
- **Recursive, bounded.** Dicts, lists, tuples, nested JSON-in-a-string where it parses cheaply.
  Depth cap (10) and size cap; cycles detected. Beyond the cap the value becomes `[truncated]` —
  never "passed through unscrubbed because it was deep".
- **One replacement token: `[redacted]`.** Never a partial mask (`abcd…wxyz`) in logs — four
  characters of a short token is a meaningful fraction of it.
- **Stable ids stay; identities go.** `user_id` is kept. Email address and IP are removed from
  Sentry events and never become log fields. The IP stays in `LoginAttempt`/`ActivityLog`, where it
  is a forensic record behind a permission, not an operational log line.
- **Modules extend the rules, never replace them.** `registry.scrub_keys.register("billing",
  {"card_number", "iban", "account_number"})`. The union is frozen at boot like every registry.
- **The frontend gets a generated copy.** `manage.py export_scrub_rules` writes
  `frontend/src/core/observability/scrub-rules.generated.json`, committed, with a CI drift check
  exactly like the OpenAPI export ([`API_PLATFORM.md`](API_PLATFORM.md)). Generated at build time
  rather than fetched at runtime because the edge runtime and the first browser error both happen
  before any API call can succeed.
- **One set of test cases for both languages.** `tests/observability/scrub-cases.json` holds
  `{input, expected}` pairs; the pytest suite and the Vitest suite both run every case. A rule that
  is fixed in one implementation and not the other fails the other suite.

**Django + Next shape.**

```python
# core/observability/scrub.py
def scrub(value, *, _depth: int = 0):
    if _depth > MAX_DEPTH:
        return TRUNCATED
    if isinstance(value, Mapping):
        return {k: REDACTED if RULES.is_sensitive_key(k) else scrub(v, _depth=_depth + 1)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, _depth=_depth + 1) for v in value]
    if isinstance(value, str):
        return RULES.scrub_text(value)        # bearer, JWT shape, URL userinfo, query values
    return value
```

```ts
// frontend/src/core/observability/scrub.ts — same algorithm, rules from the generated JSON
import rules from "./scrub-rules.generated.json";
export function scrub<T>(value: T, depth = 0): T { /* mirrors the Python, case for case */ }
```

**Enforced by.**

- `test_scrub_cases.py` and `scrub.test.ts` over the shared case file — including the negative
  cases (`token_count`, `cache_key`, `error.code` stay readable).
- `test_scrub_rules_export_is_current` — regenerates into a temp file and diffs against the
  committed file; the check uses `git ls-files --error-unmatch` so an **untracked** generated file
  fails (a `git diff`-only check is blind to untracked files and passes in exactly the state it
  ships in).
- `test_every_exit_calls_scrub` — the log formatter, `before_send`, `before_send_transaction`,
  `before_breadcrumb` and `ErrorRecorder.record` each, with a canary.

**Configurable, not hard-coded.** The core rule set is code (loosening it is a security review, not
a settings change). Module additions are registry entries. `SCRUB_MAX_DEPTH` is a constant.

---

## 4. Sentry — **Tier 2 · Core**

**What.** Optional Sentry integration, configured once in core
(`core/observability/sentry.py::init_sentry()`), active only when `SENTRY_DSN` is set; the matching
Next configuration for client, server and edge. Sentry is one **backend** of the error-reporting
facade (§ 5); the built-in tracker is the other; either, both or neither may be on.

**Why.** Error tracking is the difference between "a user reported a 500" and "we saw it, grouped
with 40 others, and it started with release X". But an error tracker is also an exfiltration channel
with a vendor's retention policy, so every default below is the conservative one.

**Rules.**

- `send_default_pii=False` · `max_request_body_size="never"` · **`include_local_variables=False` by
  default** — stack-frame locals are the most dangerous thing Sentry collects: the `password` local in
  a login function travels with the event. If an operator turns locals on (`SENTRY_INCLUDE_LOCALS`),
  `before_send` scrubs every `frames[].vars` with § 3.
- **`before_send` order:** drop → classify → scrub. Drop `Http404`/`NotFound`/`MethodNotAllowed`
  and client-disconnects; **downgrade** expected exceptions to `info` (an exception class with
  `expected = True`, or one in `registry.expected_exceptions`) and connection/timeout errors to
  `warning`; then scrub the whole event — request, headers, query string, breadcrumbs, **tags**,
  contexts, extra, span data.
- **The core exception handler must call the facade explicitly.** Django's integration hooks
  `got_request_exception`, which Django fires only when *it* converts an exception to a response. A
  DRF exception handler that returns a 500 envelope itself means that signal never fires and Sentry
  never sees the error. `core.observability.errors.report(exc, request=request)` is called from the
  handler, and it fans out to every enabled backend.
- **Trace sampling is a function, not a rate.** `traces_sampler` returns `0` for health, metrics,
  static and the schema; per-route-prefix rates from `SENTRY_TRACES_RATES`; else
  `SENTRY_TRACES_SAMPLE_RATE` (default `0.0` — tracing is opt-in, because it is the costly part).
- **One release id.** `release=APP_VERSION`, `environment=APP_ENV`. `APP_VERSION` is baked into the
  backend image and passed to the frontend build as `NEXT_PUBLIC_APP_VERSION` from the **same**
  value ([`OPERATIONS.md`](OPERATIONS.md) § 5), so source maps attach to the stack traces they
  belong to and "which release introduced this" has one answer. The boot audit warns when
  `APP_VERSION` is unset in production (it would default to `0.0.0-dev` and every release would
  look like one).
- **Frontend: the same scrubber in all three runtimes.** `instrumentation-client.ts` (browser) and
  `instrumentation.ts`'s `register()` (server and edge) all set `beforeSend`,
  `beforeSendTransaction` and `beforeBreadcrumb` to the generated-rules scrubber. A server-side
  config without `beforeSend` is the leak described in § 3.
- **Source maps uploaded, then deleted.** The Sentry auth token is a BuildKit secret, never an
  `ARG`/`ENV` (both persist in image layers); `deleteSourcemapsAfterUpload` so maps are never
  served; a build without a token still succeeds.
- **Celery:** the Celery integration captures final failures; a retried attempt is a breadcrumb,
  not an event (a task that succeeds on retry two is not an incident).
- **Never initialise Sentry in tests.** `SENTRY_DSN` is forced empty by the test settings; the
  canary tests use an in-memory transport instead.

**Django + Next shape.**

```python
# core/observability/sentry.py
def before_send(event, hint):
    exc = (hint.get("exc_info") or (None, None, None))[1]
    if isinstance(exc, DROPPED_EXCEPTIONS):
        return None
    if exc is not None and is_expected(exc):
        event["level"] = "info"
    elif isinstance(exc, (ConnectionError, TimeoutError)):
        event["level"] = "warning"
    return scrub_event(event)          # § 3, over every event section including tags
```

**Enforced by.** `test_sentry_before_send.py` (404 dropped, expected downgraded, canary scrubbed
from each event section, locals scrubbed when enabled) · `test_sentry_not_initialised_in_tests` ·
`frontend/src/test/sentry-config.test.ts` asserting the three runtime configs wire the scrubber, the
release equals `NEXT_PUBLIC_APP_VERSION`, and the delete-after-upload option is present.

**Configurable, not hard-coded.** `SENTRY_DSN` · `SENTRY_TRACES_SAMPLE_RATE` ·
`SENTRY_TRACES_RATES` (`/api/billing/=0.2,…`) · `SENTRY_INCLUDE_LOCALS` (default `False`) ·
`APP_VERSION` · `NEXT_PUBLIC_SENTRY_DSN` · `SENTRY_ORG`/`SENTRY_PROJECT` for the upload step (never
literals in `next.config.ts`).

---

## 5. The built-in error tracker — **Tier 2 · Core**

**What.** A small `core.observability` error tracker that records unhandled exceptions from
requests, tasks and commands into two tables, with triage states, regression detection and a
permission-gated admin screen — so a product with **no** monitoring vendor still gets grouped,
countable, triageable errors, and a product **with** one gets an in-app view its operators can use
without a vendor seat. Selected by `ERROR_TRACKING_BACKENDS` (`["builtin"]`, `["sentry"]`,
`["builtin", "sentry"]`, `[]`).

**Why.** Errors that live only in log files are errors nobody counts. And a triage workflow needs
states a log line does not have: "we know", "we fixed it", "it came back".

**Rules.**

- **Fingerprint = `sha256(exception_class | file | line | route)`. The message is excluded on
  purpose.** `User 41 not found` and `User 87 not found` are one bug. The stated cost: two bugs
  raised from the same line of a shared helper merge into one group — each occurrence keeps its own
  message, so the merge is visible.
- **`file` and `line` are the innermost frame in *project* code** — the deepest frame under
  `BASE_DIR` and outside `site-packages`. Otherwise every database error in the product groups at
  one line of the database driver. `file` is stored **relative** to `BASE_DIR` so a changed deploy
  path does not split every group on the next release.
- **`route`** is the URL name for requests, the task name for Celery, the command name for
  management commands.
- **Statuses: `open` · `resolved` · `ignored` · `muted`.**

  | Status | Meaning | Alerts on a new sighting? | Reopens? |
  |---|---|---|---|
  | `open` | Untriaged or being worked | First sighting only | — |
  | `resolved` | "We fixed it" | **Yes — as a regression**, a distinct alert | **Yes → `open`, `was_regression=True`** |
  | `ignored` | Triaged as not-a-bug; hidden from the default list | No | No — ignoring is a decision |
  | `muted` | Real, known, external (a flaky provider) | No, until `muted_until` | At `muted_until` it returns to `open` |

  **Only `resolved` reopens.** `muted` carries an expiry so a mute cannot quietly become permanent —
  before mutes existed, silencing a known-flaky error required a code change and a deploy.
- **Request input is never captured.** An occurrence stores method, route, path **without** its
  query string, `user_id`, `request_id`, release, message (≤ 2,000 chars, scrubbed) and stack
  (≤ 10,000 chars, scrubbed, no locals). The table is readable by anyone holding
  `core.errors.view`; it must not become a second copy of every form anyone ever submitted.
- **User-driven exceptions are not errors.** `ValidationError`, `NotAuthenticated`,
  `AuthenticationFailed`, `PermissionDenied`, `NotFound`/`Http404`, `Throttled`,
  `MethodNotAllowed`, `ParseError`, `UnsupportedMediaType` are skipped. `DisallowedHost` and
  `SuspiciousOperation` go to the `security` logger instead.
- **Record before any dedup or alert throttle,** so counts reflect reality even when alerts are
  suppressed.
- **Write on a separate connection.** The request's transaction is frequently *why* we are
  recording — it may be rolled back or in a failed state. The recorder writes through
  `OBSERVABILITY_DB_ALIAS`, a second alias pointing at the same database (created automatically as a
  mirror of `default` when not configured), so the record survives the rollback of the request it
  describes.
- **`record()` never raises.** Every failure inside it is caught and logged at `WARNING`.
  Monitoring that can crash the thing it monitors is worse than none.
- **Bounded under a storm.** The group row is upserted (`INSERT … ON CONFLICT (fingerprint) DO
  UPDATE SET occurrence_count = occurrence_count + 1, last_seen_at = now()`); occurrence rows are
  capped per group per minute (`ERROR_OCCURRENCE_RATE_PER_MINUTE`, default 10) — the count keeps
  climbing, the evidence table does not.
- **Retention:** occurrences by age **and** by a per-group cap, registered with the retention
  engine ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)); **groups are kept** — a group is the triage
  record and it is small. There is no delete endpoint for groups: deleting a group destroys the
  evidence that a bug existed.
- **Separate permissions.** `core.errors.view` (read groups and occurrences) and
  `core.errors.manage` (change status, notes, mute). Reading an error and deciding it does not
  matter are different trusts.
- **Sources:** the core DRF exception handler, Django's `got_request_exception` (for non-DRF paths
  such as the admin), Celery `task_failure` (final failure only), the core `BaseCommand` wrapper,
  and — optionally — Next server errors from `onRequestError` via an authenticated-or-anonymous,
  rate-limited, schema-validated intake that accepts `{digest, request_id, route, message}` and
  nothing else.
- **Alerting** goes through the ops-alert dispatcher ([`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md)):
  new group → one alert; regression → one alert with `was_regression`. Recording outside production
  is on by default (`ERROR_TRACKING_RECORD_NON_PROD`); **alerting** outside production is off by
  default.

**Django + Next shape.**

| `core_error_group` | | `core_error_occurrence` | |
|---|---|---|---|
| `fingerprint` | `char(64)`, unique | `group` | FK, `on_delete=CASCADE` |
| `exception_class`, `route`, `file`, `line` | the fingerprint's parts | `occurred_at` | indexed |
| `plugin` | owning module | `request_id`, `release`, `user_id` | correlation |
| `latest_message` | scrubbed, ≤ 2,000 | `method`, `path` | path without query |
| `first_seen_at`, `last_seen_at`, `occurrence_count` | counters | `message` | scrubbed, ≤ 2,000 |
| `status`, `muted_until`, `was_regression` | triage | `stack` | scrubbed, ≤ 10,000 |
| `resolved_by`, `resolved_at`, `resolved_in_release`, `notes` | provenance | `attempt` | task retries |

Endpoints: `GET /api/system/errors/` (list, filter by status/plugin/release, the standard list
pipeline), `GET /api/system/errors/<id>/`, `GET /api/system/errors/<id>/occurrences/`,
`POST /api/system/errors/<id>/status/` (`core.errors.manage`). Frontend screen under the System
area, linked from the System Health page (§ 10).

**Enforced by.** `test_error_tracker.py`: `test_fingerprint_ignores_message`,
`test_fingerprint_uses_innermost_project_frame`, `test_only_resolved_reopens`,
`test_muted_until_expiry_reopens`, `test_record_never_raises` (database unavailable → no exception
escapes), `test_recorded_inside_a_rolled_back_request` (the row exists after the request's atomic
block rolled back), `test_request_body_not_captured` (canary), `test_occurrence_rate_cap`.

**Configurable, not hard-coded.** `ERROR_TRACKING_BACKENDS` · `ERROR_TRACKING_RECORD_NON_PROD` ·
`ERROR_ALERT_ENVIRONMENTS` (default `["production"]`) · `ERROR_OCCURRENCE_RETENTION_DAYS` (90) ·
`ERROR_OCCURRENCES_PER_GROUP_MAX` (200) · `ERROR_OCCURRENCE_RATE_PER_MINUTE` (10) ·
`OBSERVABILITY_DB_ALIAS` · `registry.expected_exceptions`. The runtime-tunable ones
(recording, alert environments, retention) are settings-registry keys under `core.errors.*`.

---

## 6. Health — three rungs — **Tier 1 · Core**

**What.** Three endpoints answering three different questions, plus the `health` registry that
plugins contribute probes to. Closes `TECH_DEBT` **DB-11** and replaces the current `HealthView`.

| | **Live** `GET /api/health/live/` | **Ready** `GET /api/health/ready/` | **Components** `GET /api/health/components/` |
|---|---|---|---|
| Question | Is this process worth keeping? | Can this instance serve traffic *now*? | Which part is unwell, and how badly? |
| Used by | Container restart policy | Container `HEALTHCHECK`, rolling-swap gate, load balancer | Monitoring, System Health page, deploy verify |
| Auth | None | None | `core.health.view` — grantable to a monitoring machine principal that holds nothing else |
| I/O | **None** | Database + cache, each with a timeout | Every registered probe |
| Body | `{"status": "ok"}` | `{"status": "ok"}` or `{"status": "unavailable", "failed": ["database"]}` | `{status, release, components: {key: {status, detail, ms, critical}}, dataplane: […]}` |
| Codes | 200 | 200 / 503 | `ok` 200 · `degraded` **200** · `down` 503 |

**Why.** The current `/api/health/` is documented as liveness and actually queries the database with
no timeout — the worst of both: a slow database makes the *liveness* probe hang, and an orchestrator
restarts healthy processes because a dependency is slow. The opposite mistake is as common: a
liveness-only probe that stays green while the database is down keeps a broken instance in the load
balancer. And a readiness probe that checks a third-party provider ejects every healthy instance
the moment the provider has an outage — turning their incident into yours.

**Rules — live.**

- **No I/O at all.** It answers from memory. If the process can run Python and write a response,
  it is alive.
- **No product identity in the body.** The current view returns `"app": "DjangoBaseX"` — a core
  literal that every product would publish on an unauthenticated endpoint (§ 16).
- **`/api/health/` stays as an alias of live.** It is the URL the code serves today and the one any
  existing probe configuration points at; it answers exactly what `/api/health/live/` answers and
  never grows its own behaviour.

**Rules — ready.**

- **Database and cache, nothing else.** `SELECT 1` inside `SET LOCAL statement_timeout` and a cache
  `set`/`get` round-trip on a random key (a round-trip, not a `PING` — `PING` succeeds against a
  read-only replica and a full instance). The cache is in readiness because it is part of the
  security model ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.4): an instance that cannot reach it
  would throttle and revoke per process.
- **Every probe has a timeout** (`HEALTH_PROBE_TIMEOUT_SECONDS`, default 2) and the whole endpoint a
  budget; client-side timeouts (`connect_timeout` in DB `OPTIONS`, `socket_timeout` and
  `socket_connect_timeout` on the Redis cache) are configured globally, never unbounded.
- **Fixed-token errors.** The unauthenticated body names which dependency failed from a closed set
  (`database`, `cache`) and never carries exception text — exception text from a connection error
  includes hostnames, ports and sometimes user names.
- **Never a third-party probe, never migrations.** A provider outage is not our outage. Migration
  state belongs to the deploy driver and the doctor — in a correct rolling deploy the new instance
  never starts against unapplied migrations, and the old one legitimately sees applied migrations it
  does not know.
- **Never cached.** Readiness must reflect now.

**Rules — both public rungs.**

- **Answered by a short-circuit middleware**, `HealthShortCircuitMiddleware`, placed immediately
  after `RequestIdMiddleware`. It answers `/api/health/live/` (and its alias `/api/health/`) and
  `/api/health/ready/` before sessions,
  authentication, CSRF, throttling, the setup-wizard gate ([`OPERATIONS.md`](OPERATIONS.md) § 3),
  locale and `ALLOWED_HOSTS` validation (the container healthcheck calls `localhost`, which the
  operator's host list rightly does not contain). One structural exemption instead of seven
  separately-remembered ones — the endpoint an orchestrator depends on must not share a rate-limit
  bucket with an attacker.
- **Unversioned.** If the API ever gains `/api/v1/`, health stays where it is; orchestrator configs
  outlive API versions.
- **Still routed and named** (`core:health` for the alias, `core:health-live`, `core:health-ready`)
  so `reverse()` works and all three
  appear in the `PUBLIC_ROUTES` ledger with reasons ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2) —
  the middleware answers first, the URLconf keeps the ledger honest.
- **Excluded from** the OpenAPI schema, Sentry tracing, metrics latency histograms and the access log
  at INFO.

**Rules — components.**

- **Per component `{status, detail, ms, critical}`.** `status ∈ ok | degraded | down | unknown`.
- **Only a `critical` component can make the install `down`,** and only core dependencies are
  critical: database, cache, broker. Everything else failing is `degraded` → **200 on purpose**. A
  stopped worker is a dashboard item and an alert, not a reason for a load balancer to eject the web
  tier; a 3 a.m. page is for the database.
- **A probe never raises.** The runner catches, times and reports: a probe that raises is `down`
  (if critical) or `degraded`, with the exception type and a scrubbed message in `detail`. The
  endpoint itself never 500s — a health endpoint that fails when the thing is unwell is useless.
- **Celery is pinged twice.** The first `control.ping()` from a freshly started process routinely
  misses replies; one retry after a short pause is the measured fix (`ping(limit=1)` was measured and
  rejected — it reports healthy fleets as degraded). Beyond "a worker answers", the probe checks that
  **every declared queue has at least one worker consuming it** (`inspect().active_queues()`), since
  a live worker on the wrong queue is a silent backlog.
- **Beat is inferred, not pinged** — beat has no control channel. The probe reads the job-run
  monitor ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)): the newest recorded run of any
  enabled schedule older than `HEALTH_BEAT_STALE_SECONDS` → `degraded`; **nothing ever recorded →
  `unknown`, not `down`** (a fresh install has not run anything yet, and "never" is a different fact
  from "stopped").
- **Plugins register probes** with `critical=False` unless they are core-owned:
  `registry.health.register(HealthProbe("search", probe_search, critical=False, timeout=2.0,
  cache_seconds=30))`. `cache_seconds` protects dependencies from monitoring load; critical probes
  are never cached.
- **Includes** the release (`APP_VERSION`), the data-plane results (§ 7), and a non-critical
  `migrations` component (unapplied count) for the System Health page — informative, never
  gating.

**Django + Next shape.**

```python
# core/observability/health.py
@dataclass(frozen=True)
class HealthProbe:
    key: str
    fn: Callable[[], ProbeResult]
    critical: bool = False
    timeout: float = 2.0
    cache_seconds: int = 0

def run_probe(probe: HealthProbe) -> dict:
    started = perf_counter()
    try:
        result = call_with_timeout(probe.fn, probe.timeout)
    except Exception as exc:                          # never propagates — § 6
        result = ProbeResult("down" if probe.critical else "degraded", describe(exc))
    return {"status": result.status, "detail": scrub(result.detail),
            "ms": round((perf_counter() - started) * 1000), "critical": probe.critical}
```

**Enforced by.** `test_health.py`: `test_live_does_no_io` (database and cache patched to raise;
live still 200) · `test_ready_503_with_fixed_token_when_db_down` (body contains `database` and no
exception text) · `test_ready_exempt_from_throttle` (hammer it past every throttle rate) ·
`test_ready_answers_with_unknown_host_header` · `test_a_probe_that_raises_is_reported_not_propagated`
· `test_degraded_is_200_and_down_is_503` · `test_noncritical_failure_cannot_make_install_down` ·
`test_monitoring_principal_reads_components_and_nothing_else`. Infra policy test
([`OPERATIONS.md`](OPERATIONS.md) § 16): every proxy health location has a ready sibling; every
container `HEALTHCHECK` targets ready, not live.

**Configurable, not hard-coded.** `HEALTH_PROBE_TIMEOUT_SECONDS` · `HEALTH_READY_BUDGET_SECONDS` ·
`HEALTH_BEAT_STALE_SECONDS` (default: twice the shortest enabled schedule interval, minimum 10
minutes) · `HEALTH_CELERY_PING_TIMEOUT` · probes are registry entries; criticality is a property of
the probe, and only core may register `critical=True` (a registration-time check).

---

## 7. Data-plane self-checks — **Tier 2 · Core**

**What.** A registry of checks that verify **required rows exist and make sense** — the seed and
configuration data the product cannot function without — evaluated at boot, in the components
health endpoint, as a metric, on the System Health page and by the doctor.

**Why.** Configuration that lives in rows has no schema to fail loudly. A real incident: an admin
emptied an allow-list of permitted sign-up regions, and every sign-up was refused for five days —
invisible on every dashboard, because nothing was *broken*, the product was simply configured to
refuse everyone. Another: accounts were created with no plan and could never be provisioned; the
data was valid row by row and impossible as a whole. Types, constraints and migrations cannot catch
either.

**Rules.**

- **A check returns `ok | warn | fatal` with a detail and a remedy.** The remedy is a sentence an
  operator can act on: *"No active role is marked as the default for new users. Set one under
  Roles, or new invitations cannot be accepted."*
- **Fatal is reserved for "the product is impossible".** No active superuser; the default role for
  new accounts missing; a required vocabulary empty; the settings row core reads on every request
  absent. A feature deliberately left dormant is a `warn`, never a `fatal` — refusing to boot over a
  choice is how a check gets deleted.
- **The evaluator never raises.** A check that throws is reported as `warn` with
  `"check crashed: <ExcType>"`. A broken checker must never be worse than the gap it watches.
- **Where "fatal" bites.** In production-like environments a `fatal` result **refuses the web
  entrypoint** — `manage.py doctor --only dataplane --fatal-only` runs before `exec gunicorn`
  ([`OPERATIONS.md`](OPERATIONS.md) § 5) and in the deploy driver's validate step — and is reported
  everywhere else. It is not a Django system check run at import: system checks do not run under
  gunicorn, and a database query at settings import runs for `makemigrations` too.
- **Not enforced before first-run setup completes.** Until the setup wizard
  ([`OPERATIONS.md`](OPERATIONS.md) § 3) seals, an empty install is *expected* to fail these checks;
  the wizard is the remedy. Results are still reported.
- **Four consumers, one evaluation function.** Boot refusal, `/api/health/components/` (a
  `dataplane` section), the metric `app_dataplane_check_status{check}` (0 ok, 1 warn, 2 fatal — the
  label set is the closed set of registered keys, § 8) and the System Health page.
- **Checks are cheap.** Indexed `EXISTS` queries, never scans; the evaluator has a total budget and
  results are cached for `DATAPLANE_CACHE_SECONDS` for the non-boot consumers.

**Django + Next shape.**

```python
# core/dataplane.py — the core's own checks, registered in CoreConfig.ready()
registry.dataplane.register(DataPlaneCheck(
    key="core.active_superuser",
    description="At least one active account can administer the install.",
    fn=lambda: ok() if User.objects.filter(is_active=True, is_superuser=True).exists()
               else fatal("No active superuser.", remedy="Run manage.py bootstrap_admin."),
))
```

Plugins register their own in their `AppConfig.ready()`; a plugin check may be `fatal` only for
conditions that make **that plugin** impossible, and a fatal plugin check refuses boot only when the
plugin is enabled ([`EXTENSIBILITY.md`](EXTENSIBILITY.md) soft-disable).

**Enforced by.** `test_dataplane.py`: `test_evaluator_never_raises` · `test_fatal_refuses_web_entrypoint_in_production`
· `test_fatal_reported_not_enforced_before_setup_complete` · `test_every_check_has_a_remedy` ·
`test_metric_series_exist_for_every_registered_check`.

**Configurable, not hard-coded.** Checks are registry entries. `DATAPLANE_ENFORCE` (derived:
`is_production_like() and setup_complete`; an explicit `false` is refused by the boot audit in
production) · `DATAPLANE_CACHE_SECONDS` (60).

---

## 8. Metrics — **Tier 2 · Core**

**What.** A `core.metrics` registry through which core and modules declare counters, gauges and
histograms with **closed label sets pre-initialised at zero**; HTTP golden-signal metrics; dedicated
business and gate counters; a bridge for gauges that are computed in workers; and a `/metrics`
exporter that cannot be broken by a single bad callable.

**Why.** Metrics fail silently in two characteristic ways. **"No data" looks healthy**: a counter
that has never been incremented does not exist as a series, so an alert rule `rate(x[5m]) > 0`
has nothing to evaluate and a dashboard shows an empty panel that reads as "fine". **Grouping hides
outages**: HTTP metrics grouped as `4xx` hid a gate that was wrongly refusing a whole class of
customers with `402`/`403` for three days — the 4xx rate barely moved, because the gate's refusals
were a small share of all 4xx.

**Rules.**

- **Declare, don't create inline.** Every metric is declared at module level through
  `core.metrics` with its full label universe as tuples in code. `prometheus_client` metrics created
  ad hoc inside functions are banned (a test greps).
- **Closed label sets, pre-initialised.** At `AppConfig.ready()`, every combination of every
  declared label set is initialised at 0. The series exist from boot, so "zero" is a measured zero.
- **An out-of-set label value is a bug.** It raises in development and test; in production it maps
  to `"other"` and increments `app_metrics_label_rejected_total{metric}`. Never an unbounded label
  (user id, path, email) — cardinality is a cost that arrives as an outage of the monitoring system.
- **A cardinality budget per metric.** The product of label-set sizes must be ≤
  `METRICS_MAX_SERIES_PER_METRIC` (500), asserted at registration.
- **Dedicated business and gate counters.** Every decision that refuses a caller for a reason other
  than "the caller is wrong" gets its own counter with a closed `reason`:
  `app_authz_denied_total{reason="no_permission|not_visible|unknown_permission|inactive_user"}`,
  `app_auth_login_total{outcome="success|bad_credentials|locked|mfa_required|mfa_failed"}`,
  `app_throttled_total{scope}`, `app_feature_gate_blocked_total{gate}`,
  `app_webhook_delivery_total{outcome}`, `app_outbox_dispatch_total{outcome}`. **`unknown_permission`
  is a bug by definition** ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2) and alerts at any
  non-zero rate.
- **HTTP metrics by route name and status class, plus exact status for the gate codes.**
  `app_http_requests_total{route, method, status_class}` and
  `app_http_request_duration_seconds{route}`; unresolved routes collapse to `route="unmatched"` so a
  scanner cannot mint series.
- **Metric names are a contract, not branding.** Prefix `app_` in every product, so the shared
  alert rule pack (§ 9) works unmodified; the product is a **target label** added by the scrape
  config, never part of the name.
- **Multiple gunicorn workers need multiprocess mode.** `PROMETHEUS_MULTIPROC_DIR` is required
  when `GUNICORN_WORKERS > 1` (a system check), gauges declare a `multiprocess_mode`, and the
  directory is emptied at container start (stale files from a previous process report dead workers'
  values forever).
- **Workers are not scrape targets. Bridge through Redis.** A beat task computes worker-side gauges
  (queue depth, oldest message age, backlog counts) and writes a JSON snapshot
  `{generated_at, values}` to Redis; the web exporter exposes it through a **custom collector**
  (multiprocess mode does not support `Gauge.set_function`) with a 5-second in-process cache, plus
  `app_metrics_snapshot_age_seconds{snapshot}` so a dead bridge is itself alertable.
- **Bridge callables never raise.** A failed read reports `-1` for that gauge and increments
  `app_metrics_bridge_errors_total{snapshot}`. One exception in a collector aborts the entire
  `/metrics` response — every series, and every alert that depends on any of them, goes dark at
  once. That is the single most expensive way this subsystem can fail.
- **`app_build_info{version, env}` = 1** — the release as a metric, so every graph can be overlaid
  with deploys.
- **`/metrics` is not public.** Served only on the internal network; the edge proxy returns 404 for
  it ([`OPERATIONS.md`](OPERATIONS.md) § 14); optionally a bearer token read from
  `METRICS_TOKEN_FILE`. Throttle-exempt and excluded from tracing.

**Django + Next shape.**

```python
# rbac/metrics.py — declared once, imported for its side effect by rbac.apps
AUTHZ_DENIED = metrics.counter(
    "app_authz_denied_total", "Requests refused by authorization, by reason",
    labels={"reason": ("no_permission", "not_visible", "unknown_permission", "inactive_user")},
)

# at the point of decision
AUTHZ_DENIED.inc(reason="not_visible")
```

Exporter choice (`django-prometheus` for the HTTP/DB baseline, or `prometheus_client` alone with
core's own middleware) is a pending decision below; the registry and every rule in this section are
the same either way.

**Enforced by.** `test_metrics_registry.py`: `test_every_declared_series_exists_at_zero_on_boot` ·
`test_out_of_set_label_raises_in_test` · `test_cardinality_budget_enforced` ·
`test_metrics_endpoint_survives_a_raising_collector` (a collector that raises; `/metrics` still 200
and every other series present) · `test_no_adhoc_prometheus_metrics` (AST scan outside
`core/metrics`) · `test_multiproc_dir_required_with_multiple_workers`.

**Configurable, not hard-coded.** `METRICS_ENABLED` · `METRICS_TOKEN_FILE` ·
`PROMETHEUS_MULTIPROC_DIR` · `METRICS_MAX_SERIES_PER_METRIC` · `METRICS_BRIDGE_CACHE_SECONDS` (5) ·
the snapshot schedule is a job-registry entry. Label universes are code, by design.

---

## 9. Alerting that watches itself — **Tier 2 · Core**

**What.** A product-agnostic Prometheus rule pack and Alertmanager configuration template shipped in
`deploy/monitoring/`, with `promtool` rule tests and pytest config tests. The rules page humans (or
feed the in-app dispatcher in [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md));
**this section is about the rules that detect that alerting itself has stopped working.**

**Why.** A real incident: every receiver's destination was commented out during a migration, and
twenty-five rules fired into nothing for weeks. Every rule was correct. Nothing was delivered.
Nothing noticed, because the thing that would have noticed was the thing that was broken.

**Rules.**

- **`Watchdog`** — `vector(1)`, always firing, routed to an **external dead-man's switch** that pages
  when it *stops* receiving. The only defence against "the whole pipeline is down".
- **`AlertmanagerNotificationsNeverAttempted`** — alerts are firing but a receiver integration's
  `alertmanager_notifications_total` has not increased. This is the rule that catches a receiver
  with no destination: its *failed* counter stays at zero forever, so "notifications failing" never
  fires.
- **`AlertmanagerNotificationsFailing`**, **`AlertmanagerConfigReloadFailed`**,
  **`PrometheusNotificationQueueFilling`**, **`PrometheusAlertmanagerErrors`**,
  **`PrometheusNotConnectedToAlertmanagers`** (discovered < 1).
- **`absent()` for every target.** `TargetMissing: absent(up{job="app-web"})` beside
  `TargetDown: up{job="app-web"} == 0`. `up == 0` cannot fire once a scrape config is deleted or a
  relabel drops the target — the series simply ceases to exist.
- **Stale-or-absent for anything with a freshness timestamp.** Backups:
  `(time() - app_backup_last_success_timestamp_seconds > 26*3600) or absent(app_backup_last_success_timestamp_seconds)`
  ([`OPERATIONS.md`](OPERATIONS.md) § 9). The same shape for the metrics bridge
  (`app_metrics_snapshot_age_seconds`), beat staleness and data-plane results.
- **Core application rules** in the pack: 5xx ratio; `app_authz_denied_total{reason="unknown_permission"} > 0`;
  data-plane `fatal`/`warn`; queue depth and oldest-message age; beat stale; error-group regressions
  (from the built-in tracker's counter `app_error_groups_total{event="new|regression"}`); readiness
  failing on any instance.
- **Secrets from files.** Alertmanager receiver URLs and tokens use the `*_file` fields
  (`url_file`, `api_url_file`, `password_file`), mounted from a secrets directory — never literals in
  the config and never environment variables echoed into it.
- **Config tests.** `tests/infra/test_alertmanager_config.py` parses the rendered config and asserts:
  every receiver has at least one destination; every route's `receiver` exists; the Watchdog route
  exists and targets the dead-man receiver; **no secret literals** (no `url:`/`api_url:` on
  receivers that support `*_file`; no string matching the scrubber's secret shapes); every receiver
  that posts to the application points at a path that `reverse()` resolves.
- **Rule tests.** `promtool check rules` and `promtool test rules` in CI, with a unit test per rule
  — in particular that each `absent()` rule fires when the series is removed, which is the case the
  rule exists for and the one nobody tests by hand.

**Django + Next shape.** Files: `deploy/monitoring/prometheus/rules/{pipeline,app,infra}.yml`,
`deploy/monitoring/prometheus/tests/*.yml`, `deploy/monitoring/alertmanager/alertmanager.yml.tmpl`,
`deploy/monitoring/alertmanager/secrets/README.md` (key names only). Optional application intake:
`POST /api/ops/alerts/` (machine principal, Alertmanager webhook format) that hands alerts to the
ops dispatcher.

**Enforced by.** The two test files above, and the infra policy suite ([`OPERATIONS.md`](OPERATIONS.md) § 16).

**Configurable, not hard-coded.** Thresholds are rule-pack parameters rendered from
`deploy/monitoring/values.yml` (5xx ratio, queue age, backup age); receivers and routes are the
deployer's; the pipeline rules themselves are not optional.

---

## 10. The System Health page — **Tier 2 · Core**

**What.** An admin screen (`/system/health` in the frontend, `GET /api/system/health/` behind
`core.system_health.view`) that aggregates **registered panels** into one honest overview of the
install.

**Why.** Operators need one place to look. The two ways such a page goes wrong: it becomes a second
copy of every module (and drifts from each), or it shows green ticks for things nobody measured.

**Rules.**

- **Summaries and links, never a second copy.** The errors panel shows open groups and 24-hour
  occurrences and links to the error tracker; the jobs panel shows worker/beat health and links to
  the run monitor. It does not re-implement either.
- **Panels are registered:** `registry.system_health.register(Panel(key, label, fn, permission,
  link))`. A panel the viewer cannot open is not shown; its link is shown only if the viewer can
  open the destination (the same permission the destination checks).
- **Core panels:** database (size via `pg_database_size`, connections in use vs `max_connections`);
  **growth-prone tables** — a registered allow-list with `pg_total_relation_size` and the planner's
  row estimate (`reltuples`), **never** `COUNT(*)` on a table whose whole point is that it is large;
  disk free for media and data volumes; cache (used memory, evictions); errors; workers and beat;
  data-plane; release and last deploy; backup freshness; health components.
- **Provider probes cached.** Integration reachability panels (registered by
  [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)) are cached for
  `SYSTEM_HEALTH_PROVIDER_CACHE_SECONDS` (60) — opening the page must not hammer five third parties,
  and ten operators opening it must not hammer them ten times.
- **Every panel fails soft.** A panel function that raises or times out renders as `error` with a
  scrubbed detail; the page still renders every other panel.
- **A panel without a real probe says "pending".** Never a green tick nobody checked. A new module
  that registers a panel before its probe exists ships a panel whose state is `pending` — which is
  honest, visible and a reminder.
- **Every figure on the page is a `Figure`** (§ 11).

**Django + Next shape.** Growth-prone tables are registered by their owners:
`registry.system_health.growth_table("users_login_attempt")`. The page is a server-component shell
with one client-fetched section per panel, each in its own suspense boundary, so one slow panel does
not hold the page ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)).

**Enforced by.** `test_system_health.py`: `test_a_raising_panel_does_not_break_the_page` ·
`test_panel_without_probe_is_pending` · `test_growth_tables_never_count_star` (query capture) ·
`test_links_hidden_without_destination_permission` · `test_provider_probe_cached`.

**Configurable, not hard-coded.** Panels and growth tables are registry entries;
`SYSTEM_HEALTH_PROVIDER_CACHE_SECONDS`, `SYSTEM_HEALTH_PANEL_TIMEOUT_SECONDS` are settings-registry
keys.

---

## 11. Zero is not a fact — the figure state model — **Tier 2 · Core**

**What.** A data contract — `core.observability.figures.Figure` on the backend, the matching
TypeScript type on the frontend — that every dashboard tile, System Health figure, integration usage
count and "N items" summary uses. A figure carries its **mechanism's state** alongside its value.

**Why.** `0` is at least four different facts. "0 failed jobs" from a monitor that is running is
good news. "0 webhooks delivered" because nobody ever wired the webhook feature is not a success
metric. "0 API calls" from a surface nothing measures is a lie. A real incident: an integrations
screen under-reported traffic about 400 to 1, because a second entry point had no counter at all and
rendered as `0`. Another: the busiest integration read "never called", because "last called" was
computed as a `MAX` over the same 24-hour window as the counts.

**Rules.**

- **Five states.**

  | State | Meaning | Renders as |
  |---|---|---|
  | `live` | The mechanism is running and recorded activity in the window | the value |
  | `quiet` | Running, recorded **nothing** in the window, has recorded before (or is healthy with nothing to do) | the value (`0`), styled as calm |
  | `never` | The mechanism exists and has **never** recorded anything | "never", not `0` — a feature nobody has used, or nobody wired |
  | `off` | Deliberately disabled by a setting or flag | "off", with the setting that controls it |
  | `untracked` | Nothing measures this | **"not measured"** with `untracked_reason`; `value` is `null`, **never** `0` |

- **Untracked surfaces are listed loudly.** A summary shows "3 surfaces not measured" as a
  first-class figure with a one-click filter — it is how a missing counter becomes somebody's task.
- **Counts are windowed; recency is all-time.** `value`/`window_total` over the window;
  `last_at` over all time. A windowed `MAX` makes every quiet source look dead.
- **`window_total` and `all_time` are published separately**, and a tile never divides one by the
  other without saying so.
- **The state is computed by the mechanism's owner,** from facts it has (`enabled`,
  `count_in_window`, `ever_recorded`, `measured`) through one helper — never inferred by the
  frontend from the value.

**Django + Next shape.**

```python
@dataclass(frozen=True)
class Figure:
    value: int | float | None
    state: Literal["live", "quiet", "never", "off", "untracked"]
    window: str | None = "24h"
    window_total: int | float | None = None
    all_time: int | float | None = None
    last_at: datetime | None = None          # all-time recency
    untracked_reason: str | None = None

    def __post_init__(self):
        if self.state == "untracked" and self.value is not None:
            raise ValueError("an untracked figure has no value — never 0")
```

`FigureSerializer` in DRF; `type Figure` generated from OpenAPI on the frontend; `<StatTile
figure={…}>` ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)) renders by state and has no code path
that turns `null` into `0`.

**Enforced by.** `test_figures.py`: `test_untracked_cannot_carry_a_value` ·
`test_recency_is_all_time` (activity 30 days ago, window 24 h → `quiet` with `last_at` set, not
`never`) · a frontend test that `StatTile` renders "not measured" for `untracked` and never the
digit `0`.

**Configurable, not hard-coded.** Window lengths are per-surface settings-registry keys
(`core.dashboard.window`, default `24h`); the state vocabulary is closed and is code.

---

## 12. Doctors — **Tier 1 · Core**

**What.** `manage.py doctor` — an umbrella that runs every registered doctor, reports findings
with severities and remedies, supports `--json` for CI and the deploy driver, and exits with a
meaningful code. Individual doctors arrive with their subsystems; the umbrella and its registry
arrive first, with `permissions_doctor` ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.4) as its
first entry.

**Why.** Every subsystem eventually grows a "is this configured correctly?" question that no request
asks. A doctor per subsystem, invoked by hand, is a doctor nobody runs. One command, run by CI, by
the deploy driver and by an operator at 2 a.m., is a doctor that earns its keep.

**Rules.**

- **Registered, not listed.** `registry.doctors.register(Doctor(key, fn, owner, description,
  requires_db=True))`. The umbrella names no subsystem.
- **Findings, not prose.** Each doctor returns `Finding(severity="failure"|"advisory", code,
  subject, message, remedy)`. The message names the fix, not just the fault.
- **Delegate to the real enforcement code; never re-model it.** The permissions doctor asks
  `HasPermission` and the registry; the queue doctor asks the broker; the migrations doctor asks
  Django's `MigrationLoader` and `MigrationRecorder`. A second copy of the arithmetic will one day
  disagree with the first, and then it reports "healthy" over routes that are dead.
- **Exit codes:** `0` clean · `1` at least one failure · `2` a doctor itself crashed (reported as its
  own finding — a crashed doctor is not a passing doctor) · `3` usage error.
- **`--json`** emits a stable schema (`{doctor, findings[], backlog{size, entries_fixed[]}, duration_ms}`)
  consumed by CI and by the deploy driver's validate step ([`OPERATIONS.md`](OPERATIONS.md) § 6).
- **`--strict`** promotes advisories to failures **and** requires every backlog to be empty. CI runs
  plain `doctor` until a subsystem's ledger is empty, then that subsystem moves to `--strict`
  (`DOCTOR_STRICT_KEYS`).
- **`--only`/`--skip`** by key; `--fatal-only` for the entrypoint data-plane refusal (§ 7).
- **Never "healthy" over a backlog.** A doctor with a non-empty ledger reports
  "N known issues remain", never "healthy".

**The registered doctors (each owned elsewhere, each a thin registration here):**

| Key | Checks | Owner |
|---|---|---|
| `permissions` | § 9.4 checks — codes ↔ catalog ↔ rows ↔ routes | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) |
| `queue` | Depth, oldest message age, unregistered task names waiting in queues, `task_time_limit` ≥ broker visibility timeout (a job would run twice), queues with no consumer | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| `schedule` | Every registered schedule synced to the scheduler, overdue runs, never-recorded runs | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| `search` | Index vs source reconcile (`--reindex` to repair) | [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) |
| `docs` | Generated indexes current, internal links resolve | [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) |
| `retention` | Dry-run of every policy: rows that would go, policies over their cap | [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |
| `plugins` | Declared vs installed vs enabled, import failures, `requires` satisfied | [`EXTENSIBILITY.md`](EXTENSIBILITY.md) |
| `dataplane` | § 7 | this file |
| `migrations` | DB `django_migrations` vs the release's graph: applied-but-unknown, unapplied, multiple leaves | [`OPERATIONS.md`](OPERATIONS.md) § 8 |
| `settings` | Every registered setting is read by code; no stored key without a definition | [`CONFIGURATION.md`](CONFIGURATION.md) |
| `observability` | Scrub-rules export current, every declared metric registered, `RequestIdMiddleware` first, JSON logs in production | this file |
| `connections` | Connection budget vs `max_connections` / pooler limits | [`OPERATIONS.md`](OPERATIONS.md) § 12 |

**Backlog ledgers.** A doctor may carry a `KNOWN_<THING>` ledger — a frozenset literal in the
doctor's module — of findings that already existed when the check was introduced:

1. **A finding outside the ledger is a failure.** New breakage fails immediately.
2. **A ledger entry that no longer reproduces is a failure too** ("entry fixed or gone — remove it").
   Otherwise the ledger silently becomes decoration and its count stops meaning anything.
3. **Shrink-only.** `scripts/ledger_guard.py` in CI compares every ledger's size with the same
   file at the merge base and fails if any grew, unless the PR carries the `ledger-growth` label.
   Growing a ledger means shipping a known-broken thing, and that must be a visible decision.

**Django + Next shape.**

```python
# core/doctors.py
registry.doctors.register(Doctor(
    key="dataplane", owner="core",
    description="Required rows exist and make sense (OBSERVABILITY.md § 7).",
    fn=lambda: [finding_from(r) for r in evaluate_dataplane() if r.status != "ok"],
))
```

**Enforced by.** `test_doctor_umbrella.py`: `test_crashing_doctor_exits_2_and_is_reported` ·
`test_json_schema_stable` · `test_strict_fails_on_advisory_and_nonempty_backlog` ·
`test_fixed_ledger_entry_is_a_failure` · `test_umbrella_names_no_subsystem` (AST scan). Plus
`scripts/ledger_guard.py` in CI, with its own test using a fixture repository where a ledger grows.

**Configurable, not hard-coded.** Doctors are registry entries; `DOCTOR_STRICT_KEYS` is the list of
subsystems CI runs strictly; per-doctor thresholds (queue age, etc.) are settings-registry keys owned
by the subsystem.

---

## 13. Check hygiene — the "forty failures" rule — **Process**

**What.** The rules that decide whether a new check, doctor, alert or policy test survives contact
with a real codebase.

**Why.** A check that fails forty times on its first run gets switched off — commented out,
`continue-on-error`'d, or deleted in a hurry before a release — and a switched-off check protects
nothing. So does a check that can never fail.

**Rules.**

- **New checks ship with a baseline.** Introduce a check together with a shrink-only ledger (§ 12)
  of everything it finds today, so it fails only on *new* breakage from day one.
- **Hard failures and advisories are separate.** Failing a build over untidy-but-harmless
  configuration is how the whole check gets disabled, including its useful half.
- **Every check must be able to fail.** Each test, doctor and policy rule has a **positive
  control**: a fixture or test case where the thing it detects is present, asserting it is detected.
  A grep that cannot match, an enumeration whose universe is empty, and `grep -ql … | wc -l` (which
  always prints `0`) are the classic ways to write a check that always passes.
- **Enumerations fail on an empty universe.** A completeness check derives its universe from the
  code or the registry and asserts it is non-empty — `assert probes, "found no probes: the check is
  looking in the wrong place"` — instead of skipping.
- **No `continue-on-error`.** A non-blocking check is a check nobody reads.
- **Alerts obey the same rule.** A new alert rule starts at a threshold that does not fire on the
  current steady state, or it starts as a dashboard panel. Alerts that fire into a channel nobody
  acts on train people to leave the channel.
- **Guard modes.** A new runtime guard ships as `log_only` first where the settings registry supports
  it ([`CONFIGURATION.md`](CONFIGURATION.md)), with a metric counting what it *would* have refused,
  and moves to `enforce` when that count is understood.

**Enforced by.** Review, plus `ENGINEERING_PRACTICES.md`'s rule that every guard test lands with its
positive control in the same PR.

---

## 14. The frontend half — **Tier 2 · Core**

**What.** The observability wiring on the Next side, collected in one place so it is not rebuilt per
page. Rendering is [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)'s; the contracts are here.

**Rules.**

- **Request id:** forwarded on every server-side API call (§ 1); shown in the error state from the
  envelope's `request_id` ("Reference: 3f9c…") and, for server-component failures, alongside
  `error.digest`.
- **`instrumentation.ts`:** `register()` initialises Sentry for the server and edge runtimes with the
  generated scrubber; `onRequestError` logs `{digest, request_id, route}` as one JSON line and,
  when enabled, posts it to the error intake (§ 5).
- **`instrumentation-client.ts`:** browser Sentry with the same scrubber; `NEXT_PUBLIC_APP_VERSION`
  as the release.
- **No `console.log` of API responses** in production code (lint rule); a response is a body.
- **The session marker, CSRF and auth cookies are in the scrubber's key list** by construction
  (they come from the generated rules, which read the cookie-name settings).

**Enforced by.** `sentry-config.test.ts` (§ 4), `scrub.test.ts` (§ 3), an ESLint rule banning
`console.*` outside `src/lib/log.ts`.

---

## 15. Settings

Every key comes from `.env` via `django-environ` unless marked **registry** (runtime-editable,
[`CONFIGURATION.md`](CONFIGURATION.md)). Add each to `.env.example` with a blank or placeholder value
in the same change.

| Key | Default | Purpose | Boot audit (production-like) |
|---|---|---|---|
| `LOG_FORMAT` | `console` in development, else `json` | § 2 | **refuses `console`** |
| `LOG_LEVEL` / `LOG_LEVELS` | `INFO` / pinned library levels | § 2 | refuses `DEBUG` on `django.db.backends` |
| `LOG_SECURITY_RATE_LIMIT` | `1/min` per key | § 2 | — |
| `REQUEST_ID_HEADER` | `X-Request-ID` | § 1 | — |
| `REQUEST_ID_TRUST` | `proxy` | § 1 | **refuses `always`** |
| `APP_VERSION` | `0.0.0-dev` | release id everywhere | warns if unset |
| `SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_DSN` | empty (off) | § 4 | — |
| `SENTRY_TRACES_SAMPLE_RATE` / `SENTRY_TRACES_RATES` | `0.0` / empty | § 4 | — |
| `SENTRY_INCLUDE_LOCALS` | `False` | § 4 | warns if `True` |
| `ERROR_TRACKING_BACKENDS` | `["builtin"]` | § 5 | warns if empty |
| `ERROR_TRACKING_RECORD_NON_PROD` | `True` | § 5 — **registry** | — |
| `ERROR_ALERT_ENVIRONMENTS` | `["production"]` | § 5 — **registry** | — |
| `ERROR_OCCURRENCE_RETENTION_DAYS` / `_PER_GROUP_MAX` / `_RATE_PER_MINUTE` | `90` / `200` / `10` | § 5 — **registry** | floors: ≥ 7 days, ≥ 10 |
| `OBSERVABILITY_DB_ALIAS` | auto mirror of `default` | § 5 | — |
| `HEALTH_PROBE_TIMEOUT_SECONDS` / `HEALTH_READY_BUDGET_SECONDS` | `2` / `3` | § 6 | refuses `0` |
| `HEALTH_BEAT_STALE_SECONDS` | derived | § 6 | — |
| `DATAPLANE_ENFORCE` / `DATAPLANE_CACHE_SECONDS` | derived / `60` | § 7 | **refuses explicit `false`** |
| `METRICS_ENABLED` / `METRICS_TOKEN_FILE` | `True` / empty | § 8 | — |
| `PROMETHEUS_MULTIPROC_DIR` | empty | § 8 | **required** when `GUNICORN_WORKERS > 1` |
| `METRICS_MAX_SERIES_PER_METRIC` / `METRICS_BRIDGE_CACHE_SECONDS` | `500` / `5` | § 8 | — |
| `SYSTEM_HEALTH_PROVIDER_CACHE_SECONDS` / `SYSTEM_HEALTH_PANEL_TIMEOUT_SECONDS` | `60` / `3` | § 10 — **registry** | — |
| `DOCTOR_STRICT_KEYS` | `[]` | § 12 | — |

**Registries this file adds** (each must appear in [`EXTENSIBILITY.md`](EXTENSIBILITY.md)'s
catalogue): `health` (already planned in `CORE_ARCHITECTURE_PLAN.md` § 2) · `dataplane` · `doctors`
· `metrics` · `log_fields` · `scrub_keys` · `expected_exceptions` · `system_health` (panels and
growth tables).

**New permissions** (catalog entries, [`RBAC_DESIGN.md`](RBAC_DESIGN.md) naming): `core.health.view`
· `core.errors.view` · `core.errors.manage` · `core.system_health.view`.

---

## 16. ⚠️ Conflicts with existing docs

| # | Where | What is wrong | Fix |
|---|---|---|---|
| 1 | [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-11** | Says `/api/health/` "answers without checking the database". The code (`backend/core/views.py::HealthView`) runs `SELECT 1` and returns 503 on failure — it is a readiness probe with **no timeout** that is documented as liveness | Reword DB-11 to "`/api/health/` is a DB-touching probe with no timeout, documented as liveness; split into the three rungs of OBSERVABILITY.md § 6" |
| 2 | [`DEPLOYMENT.md`](DEPLOYMENT.md) § 3 | Lists `/api/health/` as liveness and says readiness is missing; both halves describe intent, not the code | Replace the table with the three rungs of § 6; container healthchecks target `/api/health/ready/` |
| 3 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2, `PUBLIC_ROUTES` | The `health` entry's reason — "Returns no data and reads nothing" — is false for the current view, and there is no entry for readiness | Keep `health` (true once § 6 makes it an alias of live); add `health-live` with the same reason and `health-ready`: *"Readiness: database and cache round-trip with timeouts; fixed-token errors; no detail"* |
| 4 | `backend/core/views.py` (code, not a doc) | Returns `"app": "DjangoBaseX"` from an unauthenticated endpoint — a core literal every product would publish; swallows every exception without a timeout | Removed by § 6: live returns `{"status":"ok"}`; release appears only in the permission-gated components endpoint |
| 5 | [`API_DESIGN.md`](API_DESIGN.md) § "Errors — one shape" | The envelope has no `request_id`, so a user cannot quote a reference and support cannot find the request | Add `request_id` to every error envelope (owned by [`API_PLATFORM.md`](API_PLATFORM.md)); 500 bodies especially |
| 6 | [`SECURITY.md`](SECURITY.md) § "Errors and logging" | "Redact at the formatter" covers one exit of four; Sentry events, the error tracker and the frontend runtimes bypass a formatter | Reword to "redact through the one scrubber (OBSERVABILITY.md § 3), which the formatter, Sentry, the error tracker and the frontend all call" |
| 7 | [`DEPLOYMENT.md`](DEPLOYMENT.md) § 0 blocker 4 | Correct as a gap; note that "structured logging" alone does not close it — request correlation, the scrubber and a surviving log driver are all part of it | When closing, close against §§ 1–3 of this file and [`OPERATIONS.md`](OPERATIONS.md) § 15 together |

---

## Pending decisions (for the repository owner)

1. **Exporter:** `django-prometheus` (HTTP and DB metrics for free, higher baseline cardinality) or
   `prometheus_client` alone with a core middleware (fewer series, one less dependency).
   Recommendation: `prometheus_client` alone — the registry in § 8 is the valuable part, and one
   dependency fewer in `pyproject.toml` (a protected file) is worth the ~60 lines.
2. **Default error-tracking backend:** `["builtin"]` (works with no vendor, costs two tables) or
   `[]` (off until chosen). Recommendation: `["builtin"]` — a base whose errors are uncounted by
   default is the DB-9 problem again.
3. **Log formatter:** a ~40-line core formatter (allow-list, § 2) or `python-json-logger`
   configured to the same allow-list. Recommendation: core formatter — the allow-list is the point,
   and libraries default to emitting every `extra` key.
4. **Where `/metrics` is served:** a separate internal port (a second gunicorn bind or a sidecar)
   or the main port with a token and an edge 404. Recommendation: main port + edge 404 + token file
   for Tier 2; revisit if a product exposes the app port anywhere but the internal network.
5. **Whether the Next error intake (§ 5) ships in core** or as a Tier 3 module.

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
