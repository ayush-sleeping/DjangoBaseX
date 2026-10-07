# API platform — lists, errors, machines, contracts, files

**The machinery every endpoint stands on: one list pipeline, one error envelope, one throttle contract, one way
for a machine to call the API, one generated contract with the frontend, and one safe path for files.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

## Scope — read first

**Owns:** the shared list pipeline (search, filter, sort, paginate) and the list envelope · the query-parameter
contract · the error envelope and the error-code catalogue · throttling and the `429` contract, including
per-recipient throttles for anonymous email/SMS triggers · credential kinds (first-party session vs machine
token) · machine consumers, tokens, scopes, the kill switch, the request log and acting-user delegation ·
idempotency keys for create requests · write safety (server-owned fields, strict input, machine drafts) · the
never-expose floor, external-facing payloads and the registry-driven generic read API · the route catalogue,
reverse permission index and orphan-permission test · OpenAPI quality and audience filtering · contract
generation and exported constants · upload validation, storage and private file serving · the API prefix and the
stable external-callback URL registry.

**Does not own:**

| Topic | Owner |
|---|---|
| URL shape, the base envelope, status-code meanings, 404-not-403 — the conventions this file extends | [`API_DESIGN.md`](API_DESIGN.md) |
| Authentication flows, cookies, CSRF, `required_permissions`, `PUBLIC_ROUTES`, `dbx.E00x` | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) |
| The permission model, roles, grant rules | [`RBAC_DESIGN.md`](RBAC_DESIGN.md) |
| `visible_to()`, write-path narrowing, provenance columns, audit rows | [`DATA_MODEL.md`](DATA_MODEL.md) § 5, [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |
| Registry mechanics (how a contribution is declared, sealed, enumerated) | [`EXTENSIBILITY.md`](EXTENSIBILITY.md) |
| Settings registry, feature flags, `APP_ENV`, project identity, storage backend configuration | [`CONFIGURATION.md`](CONFIGURATION.md) |
| Upstream/provider error mapping (provider 401/403 → 502), SSRF-safe HTTP client, webhooks, the job idempotency ledger, encryption | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| Health endpoints, request ids, logging, the scrubber, metrics, error tracking | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| The frontend transport, typed errors, cache layer, DataTable, cooldown UI | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| Bulk actions, import/export, money in payloads | [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) |
| The review checklist of classes these rules defend against | [`BUG_CLASSES.md`](BUG_CLASSES.md) |

---

## 0. The rules in one screen

1. **Every list goes through one pipeline** (`run_list`), used by the viewset, exports, bulk "all matching",
   search and any server-side consumer. Nothing re-implements filtering. → [§ 1](#1-the-list-pipeline--tier-1--core)
2. **Every ordering ends in a unique tiebreak.** DRF does not add one; the pipeline does, always. → [§ 1](#1-the-list-pipeline--tier-1--core)
3. **Unknown sort keys fall back to the default; unknown query parameters are a `400`.** A stale bookmark still
   renders; a typo'd filter never silently returns the unfiltered list. → [§ 2](#2-the-list-envelope-and-the-query-parameter-contract--tier-1--core)
4. **The applied search, filters, ordering and page size are echoed in `meta`.** The client never has to guess
   what the server did. → [§ 2](#2-the-list-envelope-and-the-query-parameter-contract--tier-1--core)
5. **One error envelope for everything** — DRF exceptions, Django's `Http404`, CSRF failures, oversize bodies,
   `IntegrityError`, database outages, throttles and 500s. No response under the API prefix is ever HTML or a
   bare `{"detail": …}`. → [§ 3](#3-the-error-envelope--tier-1--core)
6. **Every error code is registered**, exported to OpenAPI and the frontend, and raised somewhere. → [§ 4](#4-the-error-code-catalogue--tier-1--core)
7. **A `429` carries `retry_after_seconds` in the body and a `Retry-After` header of at least 1**, readable
   cross-origin. → [§ 5](#5-throttling-and-the-429-contract--tier-1--core)
8. **Throttles key on a verified identity or the trusted client IP — never on the raw `X-Forwarded-For`, never on
   the path.** → [§ 5](#5-throttling-and-the-429-contract--tier-1--core)
9. **An anonymous endpoint that sends a message is throttled per recipient**, keyed by HMAC, incremented whether
   or not the account exists. → [§ 6](#6-recipient-throttles-for-anonymous-messages--tier-1--core)
10. **A view declares which credential kinds it accepts; the default is session only.** A browser cookie never
    satisfies a machine endpoint; a machine token never reaches a human-only one. → [§ 7](#7-credential-kinds-first-party-session-vs-machine-token--tier-1--core)
11. **Machines are consumers named after systems, holding prefixed, hashed, expiring tokens whose scopes are
    validated at write time.** → [§ 8](#8-machine-consumers-and-tokens--tier-2--core)
12. **A token can only narrow, never widen.** Its reach is re-evaluated on every request against a live ceiling.
    → [§ 9](#9-the-authorization-model-for-tokens--tier-2--core---decision)
13. **Create requests with external or financial side effects honour `Idempotency-Key`.** → [§ 11](#11-idempotency-keys--tier-2--core)
14. **Server-owned fields are read-only in the serializer *and* forced in `perform_create`; input carrying unknown
    or read-only fields is refused.** → [§ 12](#12-write-safety--tier-1--core)
15. **No serializer can emit a password, secret, token or key fragment, whatever its `fields` say.** → [§ 13](#13-the-never-expose-floor-and-external-payloads--tier-1--core)
16. **Every permission in the catalog gates at least one route, or proves where else it is enforced.** → [§ 15](#15-route-catalogue-reverse-index-and-the-public-ledger--tier-2--core)
17. **Every OpenAPI operation publishes the permission it requires**, documents its parameters and error bodies,
    and uses only synthetic examples. → [§ 16](#16-openapi-quality--tier-2--core)
18. **The schema, the generated TypeScript and the exported constants are committed, and CI fails on drift in
    any of the three.** → [§ 17](#17-contract-generation-and-exported-constants--tier-1--core)
19. **Bytes decide a file's type; size is refused before the body is read; SVG is refused, not sanitised.** →
    [§ 18](#18-files-upload-validation--tier-1--core)
20. **Private files are served only through an authenticated view**, via `X-Accel-Redirect` or a short-lived
    presigned URL, under `Content-Security-Policy: default-src 'none'`. → [§ 19](#19-files-storage-and-private-serving--tier-1--core)
21. **The API prefix is one setting, and every path-keyed thing derives from it.** Externally registered
    callback URLs are frozen in a registry and never move. → [§ 20](#20-the-api-prefix-versioning-and-stable-external-urls--tier-1--core)

---

## 1. The list pipeline — **Tier 1 · Core**

**What.** One pure function, `run_list(queryset, spec, params) → ListResult`, that owns search, declarative
filters, allow-listed ordering with a required tiebreak, pagination and the echo of what it applied. The caller
supplies an already-scoped queryset; the pipeline never widens it. `BaseViewSet.list()` calls it, and so does
every other consumer of "the rows this list shows".

**Why.** Three failures, each observed in production code:

- **Two definitions drift.** A bulk "delete all matching" that re-implemented the list's filtering deleted rows the
  user had not seen, because one definition had a default filter the other lacked. "The drift is invisible until
  it deletes the wrong rows."
- **No tiebreak.** A list sorted by `created_at` alone, with rows inserted in one transaction, showed the same row
  on pages 1 and 2 and another row on neither. It looked like a data bug, not a pagination one.
- **A retrofitted second door.** An export built later grew its own `[:100]` cap and its own filter rules; a
  detail endpoint 404'd a valid id because it inherited a list-only default filter.

**Rules.**

- **The pipeline receives a scoped queryset and refuses an unscoped one.** `visible_to()` (DATA_MODEL § 5) returns
  a queryset that carries a scoped marker through clones; `run_list` raises `UnscopedQuerysetError` if the marker
  is absent. The scope is applied **before** search, filters and sort, so no client parameter can reach an
  excluded row and every count is honest.
- **The tiebreak is required, unique and last.** `ListSpec.tiebreak` defaults to `"pk"` and must name a unique
  column; construction fails otherwise. It is appended in the same direction as the first ordering term.
- **Ordering keys are public names, not ORM paths.** `ordering_map = {"created": "created_at", "customer":
  Sort("customer__name", nulls_last=True)}`. A raw client string never reaches `order_by()`, so `?ordering=password`
  and `?ordering=owner__password` are impossible by construction, not by review.
- **Nulls sort last in both directions** unless the spec says otherwise (`F(f).asc(nulls_last=True)` /
  `.desc(nulls_last=True)`). Rows with no value are rarely what someone sorting is looking for.
- **Unknown ordering keys fall back to the default** — not a `400`. Bookmarks and saved views outlive renamed
  columns. The fallback is visible: `meta.ordering_fallback: true` (§ 2).
- **Filters are declared, typed and allow-listed.** `Filter(param, field, lookup, type)` with `type` one of
  `exact · in · icontains · gte · lte · date_range · boolean · lookup` (values from a lookup table, see
  CONFIGURATION). An `apply=` escape hatch exists for the genuinely custom; it still receives only validated
  values.
- **Search is `icontains` across declared fields, ORed in one group**, with a minimum length (default 2) and a
  maximum (default 200). Django's `icontains` escapes `%` and `_`; anything that builds `LIKE` by hand must use the
  shared escape helper (BUG_CLASSES BC-21). Never `__regex`/`__iregex` on user input.
- **Page size is clamped to `max(LIST_PAGE_SIZE_OPTIONS)`** — the largest option the UI offers, exported to the
  frontend (§ 17). A ceiling *below* an offered size is worse than no ceiling: the pager and the rows disagree.
- **The count is of the filtered, scoped queryset.** Post-filtering a page corrupts totals ("told 40, handed 12").
  Very large tables may declare `count="estimate"` or `count="none"` (keyset pagination, below); the envelope says
  which.
- **Keyset pagination is an option for sync consumers** (`?cursor=`), ordered by `(updated_at, pk)`, with
  `?updated_since=` for incremental sync. Offset pagination stays the default for UI lists.
- **`?highlight=<public_id>`** (optional per spec) returns `meta.highlight_page`: which page of the current
  filters and ordering contains that row, computed with `ROW_NUMBER() OVER (…)`. Deep links from audit rows and
  notifications land on the right page.
- **No CRUD base class.** The pipeline is for *reads*. Real write paths — audit diffs, state machines, ceilings —
  override a generic `update()` in full, so it would be a second way of doing something.

**Django + Next shape.**

```python
# core/api/listing.py
@dataclass(frozen=True)
class ListSpec:
    ordering_map: Mapping[str, str | Sort]
    default_ordering: str                      # a key of ordering_map; checked in __post_init__
    search_fields: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    tiebreak: str = "pk"                       # must be unique; __post_init__ verifies against the model
    count: Literal["exact", "estimate", "none"] = "exact"
    highlight: bool = False

def run_list(qs: VisibleToQuerySet, spec: ListSpec, params: QueryDict) -> ListResult:
    """The only place a list is searched, filtered, ordered and paginated."""
```

`BaseViewSet` carries `list_spec: ClassVar[ListSpec | None] = None` — `None` on a view exposing `list` is a boot
failure (a new `dbx` check), the same inversion as `required_permissions`. The empty `filterset_fields` /
`ordering_fields` tuples already on `BaseViewSet` (AUTH_BLUEPRINT § 9.1) become fields of the spec; do not keep
both. The filter backend implements `get_schema_operation_parameters()` so drf-spectacular documents every
parameter from the same spec (§ 16).

Server-side consumers call it directly: `run_list(Invoice.objects.visible_to(user), InvoiceViewSet.list_spec,
params)` in an export job, a bulk action or an agent tool. The bulk-selection contract that reuses it lives in
DOMAIN_PRIMITIVES; its one rule belongs here: **a bulk request carrying `{"query": …, "exclude_ids": […],
"expected_count": N}` re-runs this pipeline and refuses with `409 selection_changed` when the count moved.**

On the frontend, the DataTable reads and writes exactly the parameter names the pipeline defines; those names
are exported constants, not literals (§ 17). FRONTEND_PLATFORM owns the table.

**Enforced by.**

- `tests/core/api/test_list_pipeline.py` — a list sorted on a non-unique column, with 3 × page-size rows sharing
  one value, is walked page by page; the union equals the set and no row repeats. **Proved red** by removing the
  tiebreak line.
- `test_list_rejects_unscoped_queryset` — passing `Model.objects.all()` raises.
- `test_unknown_ordering_falls_back_and_says_so` · `test_page_size_is_clamped_to_largest_ui_option`.
- `tests/architecture/test_list_specs.py` — every view exposing `list` has a `list_spec`; every `ordering_map`
  value resolves to a real field path; every spec's tiebreak is unique on its model.
- A ratchet scan: no `.order_by(` with a non-literal argument, and no `.filter(**request.` anywhere under
  `backend/`.

**Configurable, not hard-coded.** `LIST_PAGE_SIZE_OPTIONS` (default `[20, 50, 100]`), `LIST_DEFAULT_PAGE_SIZE`
(`20`), `LIST_SEARCH_MIN_LENGTH` (`2`), `LIST_SEARCH_MAX_LENGTH` (`200`) — settings, exported to the frontend.
Per-list specs are declarations on the view.

---

## 2. The list envelope and the query-parameter contract — **Tier 1 · Core**

**What.** API_DESIGN's envelope (`count · next · previous · results`), extended with what a table needs to
render without parsing URLs, plus an echo of what was applied.

```jsonc
{
  "count": 137, "page": 2, "page_size": 50, "num_pages": 3,
  "next": "…?page=3", "previous": "…?page=1",
  "results": [ … ],
  "meta": {
    "search": "acme",
    "filters": { "status": ["open", "pending"] },
    "ordering": "-created", "ordering_fallback": false,
    "count_mode": "exact"
  }
}
```

**Why.** Without an echo, a client that sent `?status=opne` and received 137 rows cannot tell a typo from "137 open
invoices". One studied API ignored unknown filters with a `200` and then had to document the trap: *consumers
must compare what they sent to what was applied.* That is a rule nobody follows. Rejecting is cheaper.

**Rules.**

- **Unknown query parameters are a `400`**, code `unknown_query_parameter`, with `details.allowed` listing the
  accepted names. The reserved names are `page · page_size · ordering · search · cursor · updated_since ·
  highlight`, plus the spec's declared filters. No cache-buster parameters; the transport sets headers instead.
- **Invalid filter *values* are a `400` with a field path** — `fields: {"filters.status": ["Unknown value
  'opne'."]}`.
- **`?format=` does not exist.** `URL_FORMAT_OVERRIDE = None` (§ 16: JSON only), so it is simply an unknown
  parameter.
- **Out-of-range `page` is a `404` with code `page_out_of_range`** and `details.num_pages`, so a client that
  deleted the last row on the last page can jump back instead of showing an error.
- **`meta.ordering` is the resolved public key**, never the ORM expression and never the tiebreak.
- **The envelope is identical for every list endpoint**, including machine-facing ones. One reader on the client.
- **No pagination in headers.** A total in `X-Total-Count` needs `Access-Control-Expose-Headers` or a
  cross-origin client cannot read it; the body has no such trap.

**Django + Next shape.** `core.api.pagination.DefaultPagination(PageNumberPagination)` with
`page_size_query_param = "page_size"`, `max_page_size` read from settings, and `get_paginated_response()`
building the envelope from the `ListResult`. A `StrictQueryParamsMixin` on `BaseViewSet` computes
`set(request.query_params) - allowed` before the pipeline runs.

**Enforced by.** `test_the_envelope_reports_what_was_applied`; `test_an_unknown_filter_is_refused` (walks every
registered `list_spec`, sends `?definitely_not_a_filter=1`, expects `400` — fails on an empty universe);
`test_every_list_endpoint_returns_the_envelope` (resolver walk, schema check of the body).

**Configurable, not hard-coded.** The reserved-name list is a constant in `core/api/listing.py` exported to the
frontend; plugins cannot add reserved names (they declare filters instead).

---

## 3. The error envelope — **Tier 1 · Core**

**What.** API_DESIGN § Errors defines the shape. This section makes it true for **every** response under the API
prefix, and adds what the shape was missing.

```jsonc
{
  "error": {
    "code": "validation_error",
    "message": "This request could not be processed.",
    "fields":      { "email": ["Enter a valid email address."], "lines.2.quantity": ["Must be at least 1."] },
    "field_codes": { "email": ["invalid"], "lines.2.quantity": ["min_value"] },
    "details": {},
    "request_id": "01J9Z…"
  }
}
```

`code`, `message` and `request_id` are always present. `fields`/`field_codes` appear on validation failures,
`details` when the code's catalogue entry documents it, `retry_after_seconds` on `429` and retryable `503`s.

**Why.** Three failures, each real:

- **Three envelopes coexisted** in one studied API — its own `{"error": …}`, the framework's `{"detail": …}`, and a
  third for `429`. Every client carried three parsers, and each new screen picked one.
- **The validation handler itself 500'd** on every schema with a custom validator, because a non-string object
  sat inside the error detail and JSON serialisation failed. The user never saw the validation message.
- **Messages without paths.** "Ensure this value is ≤ 2000" on a form with forty fields sent support to reproduce
  the request to find out which field.

**Rules.**

- **One handler, `core.api.exceptions.handler`, covers every source of error:**

  | Source | Status · code |
  |---|---|
  | DRF `ValidationError`; Django `ValidationError` raised by `full_clean()` in a service | `400 validation_error` |
  | `NotAuthenticated` / `AuthenticationFailed` | `401 not_authenticated` / `authentication_failed` |
  | DRF / Django `PermissionDenied` | `403 permission_denied` |
  | DRF `NotFound`, Django `Http404` | `404 not_found` |
  | `MethodNotAllowed` · `NotAcceptable` · `UnsupportedMediaType` | `405` · `406` · `415` |
  | `RequestDataTooBig`, `TooManyFieldsSent`, `TooManyFilesSent` | `413 payload_too_large` (Django would answer `400` HTML) |
  | Re-auth required (AUTH_BLUEPRINT § 6.9) | `423 reauth_required` |
  | `Throttled` | `429 throttled` (§ 5) |
  | `IntegrityError` | per the constraint registry, else `409 integrity_conflict` |
  | `OperationalError` (connection), lock/statement timeout | `503 database_unavailable` / `database_busy`, retryable |
  | Serialization failure, deadlock | `409 concurrent_update`, retryable |
  | `core.exceptions.ServiceError` and subclasses | the status and code they carry |
  | Anything else | `500 internal_error` |

- **Django-level errors are JSON too.** `handler400/403/404/500` in the root URLconf return the envelope for paths
  under the API prefix; `CSRF_FAILURE_VIEW` returns `403 csrf_failed` for them. Otherwise an unknown `/api/` URL, a
  CSRF failure or a `DisallowedHost` answers with Django's HTML page, and the frontend's typed-error decoder sees
  text.
- **`fields` values are always lists of strings.** The handler walks `detail` recursively: dict keys become
  dotted paths (`address.city`), list indices become segments (`lines.2.quantity`), every leaf goes through
  `str()`. Non-field errors use `NON_FIELD_ERRORS_KEY = "non_field_errors"`, set explicitly so it cannot drift.
  **A structured detail is never `json.dumps`-ed into `message`** — that is how raw enum codes leak into UI copy.
- **`field_codes` mirrors `fields` with DRF's `ErrorDetail.code`** (`required`, `invalid`, `min_value`, custom
  codes), so the frontend can localise without parsing prose.
- **`message` is safe to show a user.** From the exception if a service raised it deliberately, else the code's
  catalogue default (§ 4). For a `500` it is always the generic default; the exception text is logged, never
  returned.
- **`request_id` is in every error body.** For a `500` it is the only diagnostic the caller gets, and the one fact
  support needs (OBSERVABILITY owns the id).
- **Every branch calls DRF's `set_rollback()`.** DRF only does so for `APIException`; an `IntegrityError` mapped
  to `409` without it leaves an atomic block to commit half a request.
- **After a database error the handler touches the database no further.** The connection's transaction is
  broken; an audit write on it raises `TransactionManagementError` and turns a `409` into a `500`. Failure audit
  goes through the separate-connection path DATA_LIFECYCLE specifies.
- **The `500` branch reports the exception itself** — `logger.exception(...)` once, then
  `got_request_exception.send(...)` so error-tracking integrations still fire. A handler that swallows the
  exception into a clean `500` otherwise also swallows it from the error tracker.
- **Constraint names map to codes through a registry.** `registry.constraint_errors.register("users_user_email_uniq",
  field="email", code="users.email_taken", status=400)`. The handler reads the constraint name from the driver's
  diagnostic; an unregistered constraint answers `409 integrity_conflict` with no details and logs the name
  server-side. The friendly pre-check in the serializer is for the message; **the constraint is the authority.**
  On SQLite (development, ADR-0005) the name is unavailable and every violation is the generic `409`.
- **Anonymous endpoints never map a uniqueness violation to a field message** — "email already registered" on a
  public form is an enumeration oracle (BUG_CLASSES BC-11).
- **Services raise `ServiceError`, not DRF exceptions.** A service is called from views, Celery tasks and
  management commands; it must not import the HTTP layer. `ServiceError(code, message=None, details=None,
  fields=None)` with typed subclasses (`NotFoundError`, `ConflictError`, `InvalidStateError(current, allowed)`,
  `QuotaExceededError`, `UpstreamError`) carries its own status; the handler maps it. Views may still raise DRF
  exceptions for HTTP-only concerns.
- **Validation errors are echoed to the client, never logged with values.** The log line carries `{path:
  [codes]}` only. OBSERVABILITY's scrubber is the second line.

**Django + Next shape.**

```python
# core/api/exceptions.py
def handler(exc, context):
    request = context.get("request")
    for rule in _RULES:                        # ordered: most specific first; see the table above
        if isinstance(exc, rule.types):
            set_rollback()
            status, error, headers = rule.render(exc, request)
            return Response({"error": error | {"request_id": request_id()}}, status, headers=headers)
    set_rollback()
    logger.exception("unhandled", extra={"route": route_name(request)})
    got_request_exception.send(sender=None, request=request._request if request else None)
    return Response({"error": _internal_error()}, 500)
```

The frontend's `ApiError` decodes exactly this shape once, in the transport (FRONTEND_PLATFORM).

**Enforced by.**

- `tests/core/api/test_error_envelope.py::test_every_error_path_uses_the_envelope` — an unknown URL under the
  prefix, a wrong method, malformed JSON, an oversize body, a CSRF failure, a throttled call, a `ServiceError`, an
  `IntegrityError`, a simulated `OperationalError` and a test-only view that raises. Each must return
  `application/json`, the envelope, a `code` from the catalogue and a `request_id`. Runs with `DEBUG=False`.
- `test_nested_validation_errors_flatten_to_dotted_paths` and `test_a_non_string_detail_is_stringified` (a custom
  validator raising a dict of objects — the case that 500'd).
- `test_an_integrity_error_rolls_back_the_request` — two writes, the second violates a constraint, the first is
  absent afterwards.
- `test_a_500_reaches_the_error_tracker` — `got_request_exception` observed.
- A source scan: no `Response({"detail"` and no `Response({"error"` built by hand outside `core/api/`.

**Configurable, not hard-coded.** Status and default message per code live in the catalogue (§ 4); constraint
mappings in their registry. Nothing in the handler names a module.

---

## 4. The error-code catalogue — **Tier 1 · Core**

**What.** Every error code the API can emit is declared once, with its status, default message, whether it is
retryable, what `details` it carries and a remediation hint. The catalogue is exported to OpenAPI, to the
frontend and to the help pages.

**Why.** Codes typed by hand in three places drift apart: the backend adds a code, the frontend's copy map shows
"Something went wrong", and the help article cites a code that no longer exists. A registry makes all three
derived.

**Rules.**

- **Core codes are bare** (`validation_error`, `throttled`, `not_found`, …) and form a reserved list. **Module
  codes are prefixed with the module name** (`billing.insufficient_funds`), the same rule as permissions —
  enforced by the conventions test so two plugins cannot collide.
- **A code is a contract.** Renaming one is a breaking change; retire with a replacement, never reuse.
- **Every raised code is registered, and every registered code is raised somewhere** — the orphan check keeps
  the catalogue honest in both directions.
- **`details` is documented per code** (e.g. `quota_exceeded → {limit, used, resource}`), and money in `details`
  is a string with its currency (DOMAIN_PRIMITIVES).
- **The frontend's copy map is generated from the catalogue**; a server `message` still wins over the generic
  copy when present.

**Django + Next shape.**

```python
registry.error_codes.register(ErrorCode(
    code="billing.insufficient_funds", status=402, retryable=False,
    message=_("There is not enough balance to complete this."),
    details={"required": "money", "available": "money"},
    remediation="Add funds, then retry.",
))
```

drf-spectacular exposes the catalogue as a `components.schemas.ErrorCode` enum and each operation's likely codes
as `x-error-codes` (declared on the view, verified by test). `manage.py export_contracts` writes
`frontend/src/generated/error-codes.ts` (§ 17). A help centre, if a product ships one (REUSABLE_MODULES), links
`/help/errors/<code>`.

**Enforced by.** `tests/architecture/test_error_codes.py` — AST scan of every `ServiceError(`/`raise …(code=`
literal: each is registered; each registered non-core code appears in a raise site (fails on an empty universe);
every module code starts with its module's name; the generated TypeScript equals a fresh generation.

**Configurable, not hard-coded.** Messages are translatable strings; the catalogue is registry data.

---

## 5. Throttling and the 429 contract — **Tier 1 · Core**

**What.** Rate limits that hold across every worker, key on something an attacker cannot choose, are declared
per view, and answer in a way a client can act on.

**Why.** Every one of these shipped somewhere:

- **Spoofable keys.** A limiter keyed on the leftmost `X-Forwarded-For` let every request pick a fresh identity;
  every IP limit was decorative. **DRF's own default is worse**: with `NUM_PROXIES` unset, `get_ident()` returns
  the *entire* `X-Forwarded-For` header, so each forged header is a new bucket.
- **Per-process counters.** Two replicas × four workers with in-memory counters made every limit about 8× looser
  (AUTH_BLUEPRINT § 17.4 already makes the shared cache a boot requirement).
- **Per-path keys.** Keying on the concrete URL gave every `/{slug}/` its own bucket.
- **A bare 429.** The UI showed the literal "HTTP 429" next to a live button; one user fired 13 one-time-code
  sends in 43 seconds.
- **A 429 the browser cannot read.** A throttle answering before CORS headers were added reached the page as an
  opaque network error.

**Rules.**

- **Scope per view, never per path.** Every `BaseViewSet`/`BaseAPIView` has a `throttle_scope`; a view without
  one gets the `default` scope for its principal kind — DRF's `ScopedRateThrottle` silently skips unscoped views,
  which is fail-open, so it is not used directly.
- **Scopes are a registry**, not the literal `DEFAULT_THROTTLE_RATES` dict: `registry.throttle_scopes.register(
  ThrottleScope("login", rate="5/min", key="identifier+ip", sensitive=True))`. A plugin adds its own scope without
  editing the protected `settings.py`. The throttle's `get_rate()` reads the registry, not DRF's settings.
- **The sensitive list is exact.** A scope is sensitive only because it was registered so; a new route never
  inherits the loosest tier by path prefix. Every `PUBLIC_ROUTES` view must name a sensitive or explicitly
  justified scope.
- **Keys are namespaced identities:** `user:<pk>` for a verified session user, `token:<id>` *and*
  `consumer:<id>` for a machine (API_DESIGN: per credential, so one noisy integration cannot starve others),
  `ip:<client_ip()>` for anonymous. Namespacing stops user 5 and consumer 5 sharing a bucket.
- **The client IP is `core.http.client_ip()`** (AUTH_BLUEPRINT § 17.3), and nothing else. The core throttle base
  overrides DRF's `get_ident()`; a boot check refuses `NUM_PROXIES` being set (one trust setting, not two).
- **A per-user key comes only from an authenticated `request.user`.** Never decode a cookie or bearer token
  without verifying it to find "who" for a limiter key — a forged `sub` is a fresh bucket per request. DRF
  authenticates before throttling, so the rule is: do not build a limiter that runs earlier.
- **Counting is atomic.** DRF's `SimpleRateThrottle` reads the history, appends and writes it back — two
  concurrent requests both pass. Core throttles use one atomic Redis operation (a Lua check-and-increment on a
  sliding log, or `INCR` + `EXPIRE`-on-first for fixed windows).
- **A rejected request records nothing.** Being throttled must not extend the throttle: the check and the
  increment are one operation that increments only on success.
- **Health views and `OPTIONS` are exempt.** An orchestrator must not exhaust a quota; a preflight must not cost
  twice. Health views set `throttle_classes = ()`, asserted by test; CORS preflights are answered by
  `django-cors-headers` before the view, and the core throttle skips any remaining `OPTIONS`.
- **The 429 contract:**

  ```jsonc
  // 429, headers: Retry-After: 12
  { "error": { "code": "throttled", "message": "Too many requests. Try again in 12 seconds.",
               "retry_after_seconds": 12, "details": { "scope": "password_forgot" }, "request_id": "…" } }
  ```

  `retry_after_seconds = max(1, ceil(wait))`, and `Retry-After` carries the same number. A `0` invites an
  immediate retry; DRF omits the header entirely when the wait is `0`.
- **Readable cross-origin.** `CorsMiddleware` wraps DRF, so a view-level `429` carries
  `Access-Control-Allow-Origin` — state it and test it. `CORS_EXPOSE_HEADERS` includes `Retry-After` and
  `X-Request-ID`.
- **Token-accepting views may send `RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset`**, also exposed.
  Integrators pace themselves instead of discovering the limit by hitting it.
- **Store outage behaviour is declared per scope.** Sensitive scopes fall back to a per-process limiter (a speed
  bump, never "unlimited") and raise a `throttle_store_unavailable` alert; non-sensitive scopes fail open with the
  same alert. Nothing silently stops limiting.
- **Rejections are counted per scope** (OBSERVABILITY metrics) — a burst of `429`s on a token scope is how a
  leaked token shows itself.

**Django + Next shape.** `core/throttling.py`: `ScopeThrottle(BaseThrottle)` reading `view.throttle_scope`,
the registry and `client_ip()`; `DEFAULT_THROTTLE_CLASSES = ["core.throttling.ScopeThrottle"]`; cache alias
`throttle` on the shared Redis. The frontend's `useCooldown(error)` disables the submit control for
`retry_after_seconds` (FRONTEND_PLATFORM).

**Enforced by.**

- `test_a_rotating_forwarded_for_header_still_hits_429` — 12 requests to a `10/min` scope, each with a different
  leftmost `X-Forwarded-For`, from one socket peer: the 11th is `429`. **Proved red** against DRF's default
  `get_ident`.
- `test_parallel_requests_cannot_exceed_the_limit` — 50 concurrent requests against `5/min` on the real Redis
  store: exactly 5 succeed.
- `test_a_throttled_request_does_not_extend_the_window` · `test_retry_after_is_never_below_one` ·
  `test_a_429_carries_cors_headers` · `test_health_and_options_are_never_throttled`.
- `tests/architecture/test_throttle_scopes.py` — every view resolves to a registered scope; every public route
  has a sensitive or justified scope; no throttle class keys on `request.path`.

**Configurable, not hard-coded.** Rates are registry defaults, overridable per scope through the settings
registry (`security.throttle.<scope>`, CONFIGURATION); an override on a sensitive scope is validated against the
scope's declared `max_rate`, so an admin cannot switch login throttling off from a screen.

---

## 6. Recipient throttles for anonymous messages — **Tier 1 · Core**

**What.** Every anonymous endpoint that causes an email or SMS to be sent — password reset, verification resend,
invitation resend, magic link, one-time code — is limited **per recipient** as well as per IP.

**Why.** Rotating source addresses defeats an IP limit, so an attacker could flood one victim's inbox (or run up
an SMS bill) through the product's own mail system.

**Rules.**

- **The key is `HMAC-SHA256(key, normalise(recipient))`** — Django's `salted_hmac("djx.throttle.recipient", …)`.
  Redis keys and logs never contain an address or phone number.
- **Two windows:** one per event type, one global across all message-sending events for that recipient.
- **Both increment unconditionally — before the account lookup, whether or not the account exists.** Otherwise
  the limiter answers "this address is registered" by throttling only real accounts.
- **The response is identical either way**, including when throttled for the recipient: the caller learns
  nothing about whether a message was sent (AUTH_BLUEPRINT § 6.2's enumeration rule, applied to the throttle).
- **Recipients are normalised the same way the account lookup normalises them** (lower-cased, trimmed; phone
  numbers to E.164), or two spellings get two buckets.

**Django + Next shape.** `core.throttling.RecipientThrottle(event)` used as a service call inside the view, after
input validation and before the lookup:

```python
def forgot_password(request):
    email = normalise_email(serializer.validated_data["email"])
    recipient_throttle.hit("password_forgot", email)   # raises Throttled; never reveals existence
    users_services.send_reset_if_account_exists(email)
    return Response(status=204)
```

**Enforced by.** `test_recipient_throttle_counts_unknown_addresses` (an address with no account is throttled on
the same count as a real one); `test_recipient_keys_contain_no_address` (inspect Redis keys);
`tests/architecture/test_message_triggers.py` — every public route registered as `sends_message=True` in the
public-route registry calls the recipient throttle (source scan + behavioural probe), and the set is non-empty.

**Configurable, not hard-coded.** Per-event and global limits are registry entries with settings-registry
overrides (`security.recipient_throttle.<event>`).

---

## 7. Credential kinds: first-party session vs machine token — **Tier 1 · Core**

**What.** DjangoBaseX's own UI calls the API with the httpOnly session cookies of AUTH_BLUEPRINT § 6.1. Machine
callers use tokens (§ 8). The two are separate credential kinds, and every view declares which it accepts.

**Why.** In one studied API the machine endpoints accepted the session cookie too. A cookie carries no scope, so
**every browser session silently passed the scope gate**, and the reference page's "try it" button succeeded
with an empty credential box — nobody could tell what a token actually needed. The mirror failure: a leaked
read-only machine key was used to set a first password on a passwordless account, because the password endpoint
did not ask what kind of caller it was.

**Rules.**

- **`credential_kinds` on every view; default `{"session"}`.** A view is machine-reachable only when it opts in
  (`{"session", "token"}` or `{"token"}`). Forgetting closes the door — the same inversion as
  `required_permissions`.
- **A `CredentialKindAllowed` permission class runs first** and refuses a request whose successful authenticator
  is not accepted: `403 credential_not_accepted`. A cookie on a token-only view is refused; a token on a
  session-only view is refused.
- **Human-only views refuse tokens whatever their scopes.** `human_only = True` on password, MFA, re-auth,
  session management, token issuing and role assignment views — every `/api/auth/` view by default. A `*` token
  does not reach them.
- **One authenticator per kind.** Session: `CookieJWTAuthentication` (AUTH_BLUEPRINT). Token:
  `ApiTokenAuthentication`, which claims only an `Authorization: Bearer <prefix>_…` value carrying the
  configured token prefix and ignores everything else. The session class does **not** fall back to a bearer
  header (⚠️ conflict with AUTH_BLUEPRINT § 6.4 step 1 — § 21).
- **When an `Authorization` token is present, the cookie is not consulted.** A cross-site page cannot set that
  header without a preflight CORS refuses, so this opens no CSRF path; it stops one request carrying two
  identities.
- **Both authenticators implement `authenticate_header()`.** DRF downgrades `NotAuthenticated` to **`403`**
  whenever the first authenticator returns no `WWW-Authenticate` value — which silently breaks AUTH_BLUEPRINT
  § 11's "on 401, refresh once" contract: the frontend never sees a `401`, so it never refreshes.
- **JSON only.** `DEFAULT_RENDERER_CLASSES = [JSONRenderer]` in every environment — a browsable-API page in
  development and not in production is a difference tests cannot see. `DEFAULT_PARSER_CLASSES = [JSONParser]`;
  upload views opt into `MultiPartParser` explicitly. With cookie auth, accepting form-encoded bodies lets a
  cross-site HTML form reach the API as a "simple request" with no preflight; JSON-only makes the CSRF token the
  second defence rather than the only one.
- **`DEFAULT_METADATA_CLASS = None`.** `OPTIONS` answers with `Allow` and nothing else; the schema is the
  documentation, and a metadata dump of serializer fields is not.
- **The schema is served `Cache-Control: no-cache, must-revalidate`** with an `ETag`, so a reference page never
  shows the previous deploy's endpoints; the docs UI sends requests with `credentials: "omit"`.

**Django + Next shape.**

```python
class BaseViewSet(viewsets.GenericViewSet):
    credential_kinds: ClassVar[frozenset[str]] = frozenset({"session"})
    human_only: ClassVar[bool] = False
    permission_classes = [CredentialKindAllowed, IsAuthenticated, HasPermission]

REST_FRAMEWORK |= {
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.api.auth.ApiTokenAuthentication",
                                       "users.authentication.CookieJWTAuthentication"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_METADATA_CLASS": None, "URL_FORMAT_OVERRIDE": None,
    "NON_FIELD_ERRORS_KEY": "non_field_errors",
}
```

`dbx.E001` extends to require that `credential_kinds` is a subset of the known kinds, and that no `human_only`
view accepts `token`.

**Enforced by.** `test_a_browser_session_does_not_reach_a_token_only_view` · `test_a_token_does_not_reach_a_session_only_view`
· `test_a_wildcard_token_is_refused_by_every_human_only_view` (resolver walk; fails on an empty universe) ·
`test_unauthenticated_is_401_with_www_authenticate` · `test_the_api_serves_json_not_html` (a bare
`Accept: text/html` is refused `406`, not rendered) · `test_a_form_encoded_post_is_415`.

**Configurable, not hard-coded.** The token prefix comes from project identity (§ 8). The kinds are a closed
vocabulary in core.

---

## 8. Machine consumers and tokens — **Tier 2 · Core**

**What.** A machine caller is an **API consumer**: a row named after a *system* ("warehouse-sync", "website-feed"),
never a person, holding one or more **tokens**.

**Why.** Tokens outlive employment. A token owned by a person breaks the integration when they leave, or — worse
— keeps working under a name that no longer means anything, and its audit rows name a person for a machine's
action. A consumer named after the system it serves answers "what is this and who owns it" on sight.

**Rules.**

- **Consumer:** `public_id · name (unique) · description · owner_team · contact_email · is_active · service_role
  (FK Role, the ceiling — § 9) · created_by · created_at · disabled_at · disabled_reason`. **`is_active=False` is a
  kill switch that outranks every valid token**, effective within the liveness cache TTL.
- **Token:** `public_id · consumer · name · prefix (indexed) · digest (unique) · scopes (JSON list of permission
  codes, or ["*"]) · object_ceiling (JSON, § 9) · expires_at · last_used_at · last_used_ip · created_by · created_at
  · revoked_at · revoked_by · revoked_reason · rotated_from (FK self, null)`.
- **Format: `<API_TOKEN_PREFIX>_<secrets.token_urlsafe(32)>`.** The prefix is derived from the project slug
  (CONFIGURATION) and configurable — never a literal in core — so secret scanners can be taught to recognise a
  leak. The first characters after the prefix are stored in `prefix` to identify a token on screen.
- **Stored as SHA-256, compared with `hmac.compare_digest`.** A high-entropy random token does not need a slow
  hash, and it is checked on every request. Plaintext exists once: in the create response, which carries
  `Cache-Control: no-store` and is never retrievable again.
- **Expiry is required**, capped by `API_TOKEN_MAX_LIFETIME_DAYS`, and parsed as the *end* of the chosen day.
  Rotation mints a successor with the same scopes and an overlap window, then revokes the predecessor.
- **Scopes are validated at write time** against the catalogue and the grantable set (§ 9). A typo'd scope
  "reads as granted and arrives as a 403"; here it cannot be stored.
- **One issuing path.** The admin screen, the API and `manage.py create_api_token` all call
  `core.api_tokens.services.issue_token()`. Two paths issuing credentials is how one of them skips a rule — a
  CLI once stored typo'd scopes verbatim.
- **Permissions are split.** `core.api_consumers.view` · `core.api_consumers.manage` (describe, deactivate) ·
  `core.api_tokens.issue` · `core.api_tokens.revoke`. Editing a description and minting standing credentials are
  not the same act and must not ride on one checkbox.
- **`last_used_at` is written at most once a minute per token** — not a write per request — and never on a
  rejected request.
- **A request log with retention from day one:** `ApiRequestLog(token, consumer, route_name, method, status,
  duration_ms, ip, request_id, created_at)`. **No bodies and no query strings** (they carry data). Written
  best-effort, never failing the request, and bounded by age *and* row count through the retention engine
  (DATA_LIFECYCLE) — this table grows fastest exactly when something is wrong, and a burst of rejected calls is
  how a leaked token shows up.
- **Every issue, rotation, scope change, revoke and consumer (de)activation is audited.**
- **A global break-glass switch** (`API_TOKENS_ENABLED`, a settings-registry value) refuses all token
  authentication at once, answering `401 token_auth_disabled`.
- **Webhook endpoints belong to a consumer, not a user** (JOBS_AND_INTEGRATIONS).

**Django + Next shape.** `core/api_tokens/` app: `ApiConsumer`, `ApiToken`, `ApiRequestLog`; `ApiTokenAuthentication`
returning `(MachinePrincipal, token)`; `services.issue_token/rotate_token/revoke_token`; admin viewsets gated by
the split permissions. The issuing screen renders each grantable scope with its label and sensitivity from the
permission catalogue, and shows **held-but-not-implemented scopes greyed with a reason, not hidden** — hiding
them made operators think the permission did not exist.

**Enforced by.** `test_a_disabled_consumer_refuses_a_valid_token` · `test_an_expired_or_revoked_token_is_401` ·
`test_the_plaintext_is_returned_once_and_never_again` · `test_the_cli_and_the_api_share_one_issuer` (source scan:
`issue_token(` is the only `ApiToken.objects.create` caller) · `test_request_log_never_stores_bodies_or_query_values`
· `test_a_typo_scope_is_refused_at_issue`.

**Configurable, not hard-coded.** `API_TOKEN_PREFIX` (default: derived from the project slug),
`API_TOKEN_MAX_LIFETIME_DAYS` (`365`), `API_TOKEN_ROTATION_OVERLAP_HOURS` (`24`), `API_TOKENS_ENABLED`,
`API_REQUEST_LOG_RETENTION_DAYS` / `API_REQUEST_LOG_MAX_ROWS`.

---

## 9. The authorization model for tokens — **Tier 2 · Core** · ⚠️ decision

**What.** What a token may do, and how that is checked. Two designs are both defensible; mixing their
vocabularies is not. `TECH_DEBT` **DB-21**.

### Design A — machine principals with *abilities*

A machine is a principal whose `has_perm()` is always `False`. It holds **abilities** from a separate catalogue
(`reports.read`), checked by a separate `HasAbility` permission class on machine endpoints. A browser session
never holds an ability, so it can never satisfy a machine endpoint.

### Design B — scopes *are* RBAC permission codes, with two gates

A token's scopes are permission codes from the one catalogue. Every request must pass **both** gates: the token
carries the code (or `*`), **and** the token's owner holds that permission *right now*. Consequences:

- **`*` means "everything the owner holds, evaluated per request"** — never a frozen snapshot.
- **Demoting the owner narrows every token on the next call**, with no token edited.
- **Grantable = held ∩ implemented.** A scope is offered only if the issuer holds it *and* some token-accepting
  endpoint actually requires it. Granting a permission no endpoint enforces would silently widen the token the day
  an endpoint ships.
- **Object pinning is a ceiling, never a grant.** A token pinned to organisations `{3, 7}` sees the intersection
  of that set and its owner's live scope; pinning outside the owner's reach is refused at issue; an empty pin
  means "follow the owner".

### Comparison

| | A · abilities | B · permission codes, owner-bounded |
|---|---|---|
| Vocabularies | two (permissions, abilities) | one |
| What an endpoint declares | `required_permissions` *and* `required_abilities` | `required_permissions` only |
| Typo safety | needs its own `dbx.E002` twin | `dbx.E002` already covers it |
| Browser session on a machine endpoint | impossible by construction | needs § 7's credential kinds |
| Owner leaves | nothing breaks | every token dies with the owner |
| Revoking reach centrally | edit each token | edit the owner's role |
| API_DESIGN's "do not build a second authorization system" | violated | honoured |

### ✅ Recommendation — Design B's vocabulary and gates, with a *machine-owned* ceiling

Adopt B's single vocabulary and its gates, but make the ceiling belong to the **consumer**, not to a person: every
consumer has a `service_role` — an ordinary RBAC `Role` whose `audience` is `machine`. The gates become:

1. **the token carries the code** (or `*`);
2. **the consumer's service role grants it, live** — edit the role and every token of every consumer holding it
   narrows on the next request;
3. **if an acting user is present (§ 10), that user holds it too.**

This keeps one catalogue, one declaration per endpoint, one `HasPermission` (it still calls `has_perm()` and
nothing else — AUTH_BLUEPRINT § 2's seam is untouched) and one typo check, while avoiding B's weakness: nothing
breaks when a person leaves. It also avoids the rejected "hidden service `User` per integration" — the principal
is not a `User` row, has no password and no session, `is_superuser` is always `False`, and one forgotten filter
cannot turn it into a login.

```python
class MachinePrincipal:
    is_authenticated, is_superuser, is_interactive = True, False, False

    def has_perm(self, code: str) -> bool:
        if not registry.permissions.exists(code):
            return False                                        # unknown code: deny, as for users
        if not scope_allows(self.token.scopes, code):
            return False                                        # gate 1: the credential
        if code not in role_grants(self.consumer.service_role_id):
            return False                                        # gate 2: the live ceiling
        return self.acting_user is None or self.acting_user.has_perm(code)   # gate 3
```

**Rules that come with it.**

- **A machine-audience role is never assignable to a user, and a human role never to a consumer** — enforced in
  `rbac.services`, the only writer (RBAC_DESIGN). `Role.audience` is a column, not a naming convention.
- **Grantable scopes = the service role's grants ∩ implemented scopes**, where implemented means "required by at
  least one view whose `credential_kinds` includes `token`". Computed from the declarations, never listed.
- **The superuser bypass never applies to a machine.** A machine cannot reach "everything" by any path.
- **`visible_to()` must answer for a machine explicitly.** With an acting user, it evaluates as that user. Without
  one, a model returns rows only through a declared machine rule (`machine_visibility` on its scoping
  registration, DATA_LIFECYCLE) or `.none()`. The default for an unanswered principal kind is nothing.
- **Personal access tokens are optional**, not core: the same `ApiToken` with an `owner_user` instead of a
  consumer, ceiling = the user's live permissions, still refused by human-only views. A product that wants them
  adds them without a second model.

**Enforced by.** `test_a_wildcard_token_is_bounded_by_its_service_role` · `test_editing_the_service_role_narrows_live_tokens`
· `test_a_permission_no_token_endpoint_enforces_is_not_grantable` · `test_every_scope_a_token_endpoint_requires_can_be_granted`
(some service role could hold it) · `test_a_machine_is_never_a_superuser` · `test_visible_to_returns_nothing_for_an_unanswered_machine`
· `test_a_machine_role_cannot_be_assigned_to_a_user`.

**Configurable, not hard-coded.** Service roles are data; the gates are code.

---

## 10. Acting-user delegation and machine provenance — **Tier 2 · Core** (delegation optional)

**What.** Some integrations act *for a person*: a chat assistant creating a record as the colleague who asked. The
machine's token stays in `Authorization`; the person travels separately, as a short-lived acting token.

**Why.** Trusting a container-asserted email ("the request says it is for alice@…") is full impersonation the moment
the container is compromised. And audit rows that name a person for a machine's call, or a machine for a
person's intent, both mislead the next investigation.

**Rules.**

- **`X-Acting-User: <acting token>`** — minted by `POST /api/core/identity/exchange/`, which the consumer may call
  only with the `core.identity.exchange` scope. The exchange verifies proof of the person **itself**: either an
  identity-provider ID token checked locally against cached signing keys (audience, issuer, expiry, verified email,
  allowed domain), or a first-party signed assertion. It never accepts an asserted identifier.
- **The acting token is `django.core.signing` with a dedicated salt**, bound to the consumer, the user and a short
  `max_age` (default 10 minutes). Presented by another consumer, it is refused.
- **Absent is fine; malformed or expired is `401`** — never ignored and never downgraded to "no acting user".
- **Effective permission = token scopes ∩ service role ∩ the acting user's live permissions** (§ 9, gate 3), and
  row visibility is the acting user's.
- **Every audit row records both**: `actor = the user`, `via_consumer = the consumer`, `via_token = the token`.
- **Provenance is set from the principal, never from the payload.** A machine-created record gets `created_via =
  request.auth.consumer` in `perform_create`; an optional `source_ref` from the body is a *pointer*, never evidence,
  and never an idempotency key (DATA_LIFECYCLE owns the columns). A null `created_via` means "unknown", never
  "web".
- **A machine may read anonymously what its scopes allow, but may not *author* a record that needs a human owner**
  without an acting user; ownership-bearing creates without one answer `403 acting_user_required`.

**Django + Next shape.** `core/api_tokens/acting.py` (`mint_acting_token`, `resolve_acting_user`), called by
`ApiTokenAuthentication`; `ActingUserTokenSerializer` for the exchange endpoint; `ProvenanceMixin.perform_create`.

**Enforced by.** `test_an_acting_token_from_another_consumer_is_refused` · `test_a_malformed_acting_header_is_401_not_ignored`
· `test_the_acting_user_ceiling_applies` · `test_audit_rows_carry_actor_and_consumer` ·
`test_created_via_ignores_the_payload`.

**Configurable, not hard-coded.** `ACTING_USER_TOKEN_MAX_AGE` (`600`); accepted identity providers and allowed
domains are integration settings (JOBS_AND_INTEGRATIONS / CONFIGURATION), never literals.

---

## 11. Idempotency keys — **Tier 2 · Core**

**What.** A create request carrying `Idempotency-Key: <client-generated id>` is performed at most once; a retry
with the same key replays the original result.

**Why.** Networks drop responses after the server has acted. Without a key, a client that retries a payment,
an order or an external provisioning call creates two. A studied implementation that looked the key up *before*
taking a lock let two concurrent retries both pass the "not found" check; the loser hit the unique constraint as
a `500`.

**Rules.**

- **Views declare `idempotency = "required" | "optional" | None`.** `required` for creates with financial or
  external side effects (answering `400 idempotency_key_required` without one); `optional` — honoured when sent —
  for every other `POST` create; `None` elsewhere.
- **The key is scoped to the principal** (`user:<pk>` or `token:<id>`) and the route name; two callers can use the
  same string.
- **Claim first, then work.** Insert the key row (`ON CONFLICT DO NOTHING`) in its own short transaction *before*
  the handler runs; the unique constraint is the lock. Never look up and then insert.
- **The request is fingerprinted** — SHA-256 over the canonical JSON of the validated input. Same key, same
  fingerprint → replay the stored status and body with `Idempotent-Replayed: true`. Same key, different fingerprint
  → `409 idempotency_key_reused`.
- **A key still in progress answers `409 idempotency_in_progress`**, retryable, with `Retry-After`.
- **Only a final outcome is stored.** A `2xx`, or a `4xx` the client caused, is recorded and replayed. A `5xx` or
  an exception deletes the claim so the client may retry. A replay never reports a success that did not happen —
  a record since cancelled replays its original response *and* its current state is what a `GET` returns.
- **Keys expire** after `API_IDEMPOTENCY_TTL_HOURS` and are purged by the retention engine.
- **`Idempotency-Key` is in `CORS_ALLOW_HEADERS`**, or a browser client fails preflight with an error that reads
  like a network fault.
- **This is the HTTP layer.** Idempotency of background jobs, webhooks received and outbox sends is the ledger in
  JOBS_AND_INTEGRATIONS; do not build a second one for tasks.

**Django + Next shape.** `core.IdempotencyKey(principal_key, route_name, key, fingerprint, status in_progress|done,
response_status, response_body JSON, created_at, expires_at)` with `UniqueConstraint(principal_key, route_name,
key)`; an `IdempotentCreateMixin` wrapping `create()`. The frontend transport generates a key per user-initiated
submit and reuses it across its own retries (FRONTEND_PLATFORM).

**Enforced by.** `test_two_concurrent_requests_with_one_key_create_one_row` (threads against PostgreSQL) ·
`test_same_key_different_body_is_409` · `test_a_5xx_releases_the_key` · `test_required_idempotency_refuses_a_missing_key`
· `tests/architecture/test_idempotency_declared.py` — every view registered as having external or financial side
effects declares `required`.

**Configurable, not hard-coded.** `API_IDEMPOTENCY_TTL_HOURS` (`24`).

---

## 12. Write safety — **Tier 1 · Core**

**What.** Three rules that decide what a client can change: server-owned fields are never client-writable, input
the serializer does not expect is refused, and machine-created records start where a human must look at them.

**Why.** API_DESIGN calls payload-supplied ownership "the most common DRF authorization bug". Its siblings: a
machine integration that could create an `APPROVED` record, skipping the approval path, notifications and money
checks gated on the pending state; and a hidden form section whose column the host still accepted, so a
hand-crafted request set a field the operator was never shown.

**Rules.**

- **Server-owned fields are `read_only` in the serializer and forced in `perform_create`/`perform_update`** from
  `request.user`, the principal, the scoped parent and the state machine: `owner`, `created_by`, `organisation`,
  `status`, `created_via`, `approved_at`, totals. Both — the serializer stops the value arriving; the service
  stops a second serializer forgetting.
- **Unknown input fields are a `400 unknown_field`, and so are read-only fields sent as input**
  (`field_not_writable`). DRF drops both silently; API_DESIGN § Requests already asks for rejection. A client
  that sends `status` learns immediately that it cannot set it, instead of believing it did.
- **Writable related fields are scoped.** A `PrimaryKeyRelatedField(queryset=Project.objects.all())` lets a user
  attach another tenant's project by id. Core provides `ScopedRelatedField`, whose queryset is
  `Model.objects.visible_to(request.user)`; a boot check refuses a writable related field built on an unscoped
  manager.
- **Field-level permissions strip, then reject.** `Meta.field_permissions = {"cost_price": "billing.costs.edit"}`
  removes the field for callers without the permission, and the same metadata tells the frontend what to render.
  Contributed form sections declare their fields the same way, so the host strips what the caller was never shown
  without knowing which plugin declared it.
- **Machine creates land in the model's initial state.** A token-authenticated create of a model with a state
  machine is created in its declared initial state regardless of input; transitions flagged `human_only` refuse a
  machine principal. The commercial and approval guards live on the submit path, which a human takes.
- **No `fields = "__all__"`, ever** (§ 13).

**Django + Next shape.** `core.api.serializers.StrictModelSerializer` (unknown and read-only input refused,
field permissions applied, never-expose floor applied); `ScopedRelatedField`; `perform_create` in `BaseViewSet`
calling `self.server_owned(serializer)` which each view implements. The state-machine helper and its `human_only`
flag live in DOMAIN_PRIMITIVES.

**Enforced by.** `test_owner_in_the_payload_is_refused_and_ignored` · `test_a_writable_related_field_cannot_attach_another_tenants_row`
· `test_a_token_cannot_create_an_approved_record` · `tests/architecture/test_serializers.py` — every serializer
used by a writable view subclasses `StrictModelSerializer`; no writable related field uses an unscoped queryset
(introspection of `get_fields()` on every registered viewset's serializer).

**Configurable, not hard-coded.** Field permissions are declarations; the codes come from the catalogue.

---

## 13. The never-expose floor and external payloads — **Tier 1 · Core**

**What.** A floor under every serializer: some fields cannot leave the process whatever a developer wrote. Plus a
stricter discipline for payloads that leave the organisation.

**Why.** In one studied platform, 100 of 105 resources exposed through a generic API had no field allowlist:
granting read on quotes granted the entire cost and margin model. "The registry was the only thing standing
between a typo and a credential dump." Elsewhere, a key-name check for forbidden fields passed while the same
value sat in a nested list and in a free-text notes column.

**Rules.**

- **The floor is name-based and unconditional.** Any field whose name equals or contains `password`, `secret`,
  `token`, `api_key`, `private_key`, `otp`, `recovery_code`, `digest`, `hash`, `ciphertext` or `_encrypted` is
  removed by `StrictModelSerializer.get_fields()` — and in `DEBUG`/test it raises instead, so the mistake is seen
  where it is made. Genuine exceptions (a `token_expires_at`) are allow-listed by exact name in one reviewed
  constant.
- **`fields = "__all__"` and `exclude = …` are refused** by a system check. An allowlist admits nothing new when a
  column is added; a denylist admits everything.
- **External-facing records get exactly two serializations** — a list row and a detail — both explicit
  allowlists, with no third "lightweight" endpoint that someone forgets to review.
- **External payload safety is asserted by property, not by key list.** A shared helper walks the payload
  recursively, including nested lists and free text, and applies a predicate ("no value equals a cost price", "no
  string contains an internal hostname"). Free-text fields are assumed capable of carrying the secret.
- **Secrets are never returned by a read.** A credential screen shows "set / not set"; revealing a value is a
  separate audited action behind re-auth (JOBS_AND_INTEGRATIONS).

**Django + Next shape.** `StrictModelSerializer` (§ 12) applies the floor; `core.testing.assert_no_forbidden_values(payload,
predicate)`; a `dbx` system check over every serializer reachable from a registered view.

**Enforced by.** `test_the_floor_strips_secret_fields` · `test_all_fields_is_a_boot_error` ·
`tests/architecture/test_never_expose.py` — renders every registered list/detail endpoint for a seeded object
graph whose secret columns hold canary values, and asserts no canary appears anywhere in any response.

**Configurable, not hard-coded.** The fragment list and the exact-name exceptions are constants in core,
reviewed like the permission catalogue; products may add fragments through a registry but never remove core's.

---

## 14. The registry-driven generic read API — **Tier 3 · Module**

**What.** An optional module that exposes registered models read-only to machine consumers without writing a
viewset per model: `registry.api_resources.register(...)` declares the model, its field allowlist, filterable and
orderable fields, related resources, the permission, page caps and a description.

**Why.** Integrations need "give me the orders updated since yesterday" for dozens of models. Hand-written
endpoints for each are how the second product ends up with 40 inconsistent ones. The generic engine is only safe
with the rules below; every one of them was a real leak or outage where it was missing.

**Rules.**

- **`fields` is required, and `None` is refused at registration.** One studied engine treated "no allowlist" and
  "empty allowlist" alike, and turned fail-closed into whole-table. Here `None` is a `TypeError`; `[]` means
  "public id only".
- **The query selects only the allowlist** (`.only(*fields)`), never all columns shaped afterwards.
- **Related resources serialise through their own registration.** An unregistered related model renders as its
  public id only; there is no inline expansion of an unregistered model.
- **The never-expose floor (§ 13) applies regardless of the registration.**
- **Rows come from the list pipeline (§ 1) over `visible_to(principal)`.** No second scoping path.
- **A resource whose model is not installed is hidden from discovery**, rather than advertised and then `500`ing.
- **Keyset pagination and `updated_since=`** are the default for this surface; `ETag` is computed over content
  excluding volatile fields such as `generated_at`, so an unchanged page returns `304`.
- **The permission is a catalogue code**, so § 9's gates and § 15's reverse index cover it without special cases.

**Django + Next shape.** A plugin (`djx_resource_api`, REUSABLE_MODULES) with `ResourceViewSet` building a
`StrictModelSerializer` subclass per registration at seal time (not per request), mounted under
`<API_PREFIX>resources/<key>/`, `credential_kinds = {"token"}`.

**Enforced by.** `test_a_registration_without_fields_is_refused` · `test_an_unregistered_relation_renders_only_its_id`
· `test_the_floor_applies_to_registered_resources` · the § 13 canary test extended to every registered resource.

**Configurable, not hard-coded.** Registrations are code declarations in each module; page caps per resource.

---

## 15. Route catalogue, reverse index and the public ledger — **Tier 2 · Core**

**What.** A machine-readable catalogue of every route — name, methods, actions, required permissions, public or
not, credential kinds, throttle scope, idempotency, audience — with a reverse index answering **"what does this
permission open?"**, exposed as `manage.py routes` and a read-only admin endpoint.

**Why.** OpenAPI says nothing about which permission a route requires, which is "the single most useful fact
about an endpoint here". And the roles screen needs the reverse question: an operator ticking a box should be able
to see which screens and endpoints it opens.

**Rules.**

- **The catalogue is built from the same declarations enforcement reads** (`required_permissions`, `public`,
  `credential_kinds`, `throttle_scope`) by walking the resolver — it never re-models resolution (AUTH_BLUEPRINT
  § 9.4 rule 1).
- **Every catalog permission gates at least one route, or is listed in `ENFORCED_ELSEWHERE` with a proof.** A
  permission used only in a `visible_to()` rule, a nav section or a field permission names that use, and a
  check verifies the claim; a claim that has since gained a route, or whose proof no longer holds, fails as stale.
  A permission that gates nothing implies a control that does not exist.
- **The public ledger is asserted in both directions.** Every route in `PUBLIC_ROUTES` (made registrable in
  EXTENSIBILITY, `TECH_DEBT` **DB-22**) exists and carries a reason; no route outside the ledger answers an
  unauthenticated call with anything but `401`/`403` (AUTH_BLUEPRINT § 9.3); the ledger's size is snapshotted, so
  growth is a reviewed diff.
- **Ungated-but-authenticated routes are listed first** on the admin page — the ones most worth a second look.
- **The admin endpoint is gated** (`core.routes.view`) and orders its output stably, so the page does not reshuffle.

**Django + Next shape.** `core/api/catalogue.py::build_catalogue()` shared by `manage.py routes [--json]
[--permission CODE]`, `permissions_doctor`, the OpenAPI postprocessing hook (§ 16) and
`GET <API_PREFIX>core/routes/`. The roles screen shows, beside each permission, the routes it opens.

**Enforced by.** `tests/architecture/test_permissions_gate_something.py` (orphan check with proven exceptions;
fails on an empty universe) · `test_public_ledger_both_directions` · `test_public_ledger_size_snapshot`.

**Configurable, not hard-coded.** `ENFORCED_ELSEWHERE` is a registry each module contributes to, each entry
carrying its proof callable.

---

## 16. OpenAPI quality — **Tier 2 · Core**

**What.** drf-spectacular generates the schema; this section makes the result trustworthy, and filters it by
audience.

**Why.** "A wrong schema is worse than none" (API_DESIGN). The specific ways it goes wrong: integrators learn an
endpoint's required permission from `403`s; examples copied from a database publish real names on a public page;
tags read as raw app labels; the version prefix appears in both `servers` and every path (`/api/v1/api/v1`); a
security scheme is advertised that no caller can supply (an httpOnly cookie).

**Rules.**

- **Every operation publishes what it requires** — a postprocessing hook adds `x-required-scope` (the permission
  codes the action requires; under § 9 these *are* the token scopes, so one name serves both audiences),
  `x-public`, `x-credential-kinds`, `x-throttle-scope`, `x-idempotency` and `x-error-codes` from the view's
  declarations (the catalogue of § 15). A description sentence states the permission in prose too. An
  integrator should never learn an endpoint's requirement from a `403`.
- **Keep the default postprocessing hooks.** Overriding `POSTPROCESSING_HOOKS` replaces drf-spectacular's enum
  post-processor unless it is listed again; stable names come from `ENUM_NAME_OVERRIDES`, never hash-suffixed.
- **Every list documents its query parameters** — from the `ListSpec`, via the filter backend's
  `get_schema_operation_parameters()`, each with a type, an example and `required` stated.
- **Every operation documents its success body and its error bodies**, the latter as the shared `Error`
  component (§ 3); `401`, `403`, `404`, `429` on everything non-public.
- **Examples are synthetic, never from a database.** Generated from field names and types.
- **Tags come from the module's registered label**, never a raw Django app label.
- **Paths are relative to `servers[0].url`, stated once.**
- **Only schemes a caller can supply are advertised:** the bearer token scheme for the integrator audience; the
  cookie scheme is internal-only.
- **Audience filtering.** Views declare `schema_audience = "internal" | "integrator" | "public"` (default
  `internal`). A preprocessing hook serves `/api/schema/?audience=integrator` with only token-accepting and public
  operations; unreferenced components drop out with them. The committed schema (§ 17) is the full internal one.
- **Generation emits zero warnings** (`--fail-on-warn`); every operation has a unique `operationId` and a
  description from its docstring.
- **The schema is served only when `DEBUG` or `SCHEMA_PUBLIC`** (AUTH_BLUEPRINT's public ledger), with the cache
  headers of § 7.

**Django + Next shape.** `SPECTACULAR_SETTINGS` with `COMPONENT_SPLIT_REQUEST=True`, `SERVE_INCLUDE_SCHEMA=False`,
`PREPROCESSING_HOOKS=["core.api.schema.filter_by_audience"]`, `POSTPROCESSING_HOOKS=[
"drf_spectacular.hooks.postprocess_schema_enums", "core.api.schema.annotate_requirements"]`.

**Enforced by.** `tests/architecture/test_openapi_quality.py`: `test_every_operation_publishes_the_scope_it_requires` ·
`test_every_list_operation_documents_its_query_parameters` · `test_every_operation_documents_error_bodies` ·
`test_no_tag_is_a_raw_app_label` · `test_no_example_is_copied_from_the_database` (seeds canary rows, then asserts
no canary string is in the schema) · `test_the_prefix_is_stated_once` · `test_only_suppliable_schemes_are_advertised`
· `test_integrator_audience_contains_only_token_or_public_operations` · CI runs `manage.py spectacular --validate
--fail-on-warn`.

**Configurable, not hard-coded.** `SCHEMA_PUBLIC` (default `False`); the API title derives from project identity.

---

## 17. Contract generation and exported constants — **Tier 1 · Core**

**What.** The frontend's types and constants are generated from the backend, committed, and checked three
independent ways. Closes `TECH_DEBT` **DB-4**.

**Why.** A hand-written client "typechecks against yesterday's contract". An audit of one studied frontend found
it calling endpoints that did not exist and sending parameter names the backend ignored. Elsewhere, five backend
call sites and the frontend each held their own copy of a billing constant; the copies disagreed, and quotes and
invoices disagreed with them. And a drift guard built on `git diff` passed unconditionally, because `git diff` is
blind to a file that was never committed.

**Rules — the three checks.**

1. **Static schema export, diffed.** `manage.py spectacular --file backend/openapi.yaml --validate --fail-on-warn`
   builds the schema from route definitions alone — no database, no running server (a build that reaches a live
   backend generates types from whatever version happens to be running). CI fails if the committed file differs.
2. **Generated TypeScript, committed and checked.** `openapi-typescript backend/openapi.yaml -o
   frontend/src/generated/api.d.ts`; CI runs `git ls-files --error-unmatch` on it (fails if untracked) **and**
   `git diff --exit-code` (fails if stale). The check runs before `typecheck`.
3. **Bidirectional key-set assertions.** Where the UI narrows a generated type (`CurrentUser` for the shell),
   `frontend/src/lib/api-contract.ts` asserts the key sets are equal in **both** directions and that narrowed
   fields stay assignable. The assertion returns a tuple naming the offending key, not `false`. A field the backend
   *added* is the one usually missed; the first run of this check in one studied codebase found a field the UI
   declared and the backend never sent.

**Rules — exported constants.**

- **`manage.py export_contracts`** writes `frontend/src/generated/contracts.ts`: permission codes, error codes
  (§ 4), `TextChoices` marked for export, lookup kinds, list parameter names and page-size options (§ 1–2), upload
  limits per purpose (§ 18), throttle scope names, `API_PREFIX` (§ 20).
- **"Generated == generator."** A pytest runs the exporter into a temporary directory and compares it with the
  committed file.
- **The frontend never re-declares a generated value.** A lint rule bans string-literal permission codes in
  `can("…")` calls; they must reference the generated constant.
- **A parity test never skips in CI.** A cross-stack check that cannot find the other tree fails with "the
  universe is empty", it does not skip — skipping is how such tests go silent forever.

**Django + Next shape.** `frontend/package.json` gains `codegen` and `codegen:check` scripts (protected file —
with the owner's confirmation, per `AGENTS.md`). The CI frontend job order: `npm ci` → `codegen:check` →
`typecheck` → `lint` → tests → build.

**Enforced by.** The three CI checks above; `tests/architecture/test_contracts_are_current.py`; the lint rule.
Each is **proved red** once by committing a deliberate serializer change without regenerating.

**Configurable, not hard-coded.** Which choices are exported is a marker on the declaration, not a list in the
exporter.

---

## 18. Files: upload validation — **Tier 1 · Core**

**What.** One validation path for every upload, driven by a per-purpose policy registry: `validate_upload(file,
purpose)`.

**Why.** Support attachments and screenshots in one studied platform were accepted with no validation at all;
elsewhere the type came from the filename. The classic results: HTML uploaded as `avatar.png` and served from the
application's own origin; a 30,000 × 30,000 PNG that is a few kilobytes on the wire and gigabytes in memory; an SVG
that runs script when navigated to directly.

**Rules.**

- **Bytes decide the type.** A signature table in core (PNG, JPEG, GIF, WEBP — which needs two offsets — PDF,
  ZIP-container office formats, OLE2) checked against the file's first bytes; the client's filename and
  `Content-Type` are ignored for the decision. Containers that legitimately share a signature are expected to.
- **Size is refused before the body is read.** ⚠️ **`FILE_UPLOAD_MAX_MEMORY_SIZE` is not a cap** — it is the
  threshold above which Django spools to disk, and files of any size are still accepted. Core adds an upload
  handler that raises `StopUpload(connection_reset=True)` once a policy's `max_bytes` is exceeded, alongside the
  proxy's `client_max_body_size` (OPERATIONS).
- **Count and total are capped separately.** "25 MB each" says nothing about 200 of them.
  `DATA_UPLOAD_MAX_NUMBER_FILES` bounds the request; the policy bounds the purpose.
- **Images are decoded and re-encoded.** Pillow opens with a pixel cap (`Image.MAX_IMAGE_PIXELS` lowered from
  settings), `verify()`s, re-opens, applies orientation, and saves a fresh file **without metadata** — which also
  strips location data from phone photos. Only the re-encoded bytes are stored.
- **SVG is refused, not sanitised.** Sanitisers are one bug from failing; a policy that genuinely needs SVG
  (a brand logo) must also be served under § 19's CSP, and says so in its registration.
- **The stored name is generated** (`<purpose>/<yyyy>/<mm>/<uuid>.<ext from sniffed type>`). The original filename
  is kept as sanitised metadata for `Content-Disposition` only; it never reaches a path.
- **Malware scanning is an optional hook** (`registry.upload_scanners`, e.g. a `clamd` adapter). A policy may
  require it; a required scan with no reachable scanner refuses the upload with `503 upload_scanner_unavailable`
  — it never stores unscanned bytes as clean. A scanner *error* is a distinct verdict from *clean*.
- **Two-step attach.** Upload returns a file `public_id`; the create/update payload references it; the server
  verifies the file was uploaded by the same principal, for a matching purpose, and is not yet attached. An
  uploaded-but-never-attached file is purged after `FILE_ORPHAN_TTL_HOURS`.
- **Rejections carry one code with a reason** — `upload_rejected` with `details.reason ∈ {type, size, count,
  total, pixels, scan, purpose}`.

**Django + Next shape.**

```python
registry.upload_policies.register(UploadPolicy(
    purpose="users.avatar", types=("image/png", "image/jpeg", "image/webp"),
    max_bytes=2 * MB, max_pixels=16_000_000, reencode=True,
    max_count=1, storage="private", scan="optional",
))
```

`core/files/validation.py`, `core/files/handlers.py` (the upload handler), `core/files/signatures.py`. Upload
views set `parser_classes = [MultiPartParser]` and `idempotency = "optional"`. The frontend reads limits per
purpose from the exported contract (§ 17) and validates client-side as a courtesy.

**Enforced by.** `test_html_renamed_png_is_refused` (the BUILD_ORDER 9.2 acceptance) · `test_an_oversize_upload_is_cut_off_before_it_is_read`
· `test_a_pixel_bomb_is_refused` · `test_reencoding_strips_metadata` · `test_svg_is_refused_by_default` ·
`test_a_required_scan_with_no_scanner_refuses` · `test_a_file_uploaded_by_another_principal_cannot_be_attached` ·
`tests/architecture/test_upload_views.py` — every view accepting `MultiPartParser` names a registered policy.

**Configurable, not hard-coded.** Per-purpose policies are registry entries; global defaults `IMAGE_MAX_PIXELS`,
`FILE_ORPHAN_TTL_HOURS` (`24`), `DATA_UPLOAD_MAX_NUMBER_FILES` are settings.

---

## 19. Files: storage and private serving — **Tier 1 · Core**

**What.** A storage abstraction in which private files are **never** reachable by URL guessing, whichever backend
is configured.

**Why.** In one studied deployment, object-storage mode was private with presigned URLs, while filesystem mode
served `/media/` directly from the proxy with no authentication — and the uploads included signatures and signed
documents. The security posture depended on a storage toggle.

**Rules.**

- **Django `STORAGES` has `default` (private) and `public` aliases.** Only genuinely public assets (a logo on the
  sign-in page) go to `public`. `MEDIA_ROOT` is never served by the proxy.
- **Every stored file has a row:** `StoredFile(public_id, purpose, storage_key, content_type (sniffed),
  size, sha256, original_name, uploaded_by, owner_type, owner_id, scan_status, created_at)`.
- **Access is decided by the owning object.** `GET <API_PREFIX>core/files/<public_id>/content/` resolves the owner
  through a registry of attachable models and serves only if `owner_model.objects.visible_to(principal)` contains
  it. An unregistered owner, or an invisible one, is `404`.
- **Serving mode is a setting, never a different security posture.** `x-accel`: Django authorises, then returns
  `X-Accel-Redirect` to an `internal` proxy location. `presigned`: Django authorises, then `302`s to a URL valid
  for `FILE_PRESIGNED_URL_TTL` seconds, signed for the browser-reachable endpoint rather than the internal one.
  `stream`: development only, refused by the boot audit outside `APP_ENV=development`.
- **Served user files carry `Content-Security-Policy: default-src 'none'; sandbox`, `X-Content-Type-Options:
  nosniff`, `Cross-Origin-Resource-Policy: same-site`, the sniffed `Content-Type`, and `Content-Disposition:
  attachment`** except for an allow-listed set of inline types (raster images, PDF). The proxy's internal location
  adds the same headers, so the protection does not depend on which layer answers.
- **`Cache-Control: private, no-store`** on the authorising response; presigned URLs are short-lived instead of
  cacheable.
- **A separate cookieless origin for user content is the stronger deployment** (OPERATIONS) and recommended when
  a product serves user HTML-like content inline at all.
- **Downloads never pass through the Next.js server.** A server component cannot forward the httpOnly cookie
  implicitly (AUTH_BLUEPRINT § 6.1); the browser requests the API URL directly.
- **Deletion removes the object before the row**, and a row whose object cannot be deleted is retried, never
  half-erased (DATA_LIFECYCLE retention).

**Django + Next shape.** `core/files/` app: `StoredFile`, `FileContentView`, `registry.attachable_models`;
the runtime-resolved storage backend and its settings screen are CONFIGURATION's. The frontend renders file links
from the `public_id` and the exported prefix.

**Enforced by.** `test_a_guessed_storage_key_is_not_reachable` (no URL pattern or proxy route exposes storage keys)
· `test_a_file_of_an_invisible_owner_is_404` · `test_served_files_carry_the_sandbox_csp` ·
`test_stream_mode_is_refused_outside_development` · `test_presigned_urls_expire` · an OPERATIONS policy test that
the proxy config has no public `/media/` location.

**Configurable, not hard-coded.** `FILE_SERVE_MODE` (`x-accel` in production), `FILE_ACCEL_PREFIX`,
`FILE_PRESIGNED_URL_TTL` (`60`), `FILE_INLINE_TYPES`.

---

## 20. The API prefix, versioning and stable external URLs — **Tier 1 · Core**

**What.** One setting for the API mount point, from which every path-keyed thing derives, and a frozen registry for
URLs that third parties have written into their own dashboards.

**Why.** When one studied core moved its routes from `/api` to `/api/v1`, three things broke silently: the refresh
cookie's `Path` (every session would have died after an hour), the rate-limit tier table keyed on literal paths
(credential endpoints would have dropped from 10/min to 300/min), and the HTTP client's own refresh/logout guards
(an infinite refresh loop). Separately, payment-gateway webhook and identity-provider redirect URLs are configured
in someone else's dashboard; moving one breaks an integration with no error on our side.

**Rules.**

- **`API_PREFIX` (versioned resource routes, default `"api/"`) and `API_ROOT` (unversioned mounts — health,
  schema, external callbacks — default `"api/"`) are settings.** API_DESIGN's "no `/v1/` until the first external
  consumer" stands; this makes adding it one line plus an ADR.
- **Everything derives:** the root URLconf includes, the auth cookie `Path`s (AUTH_BLUEPRINT § 6.1), OpenAPI
  `servers`, the frontend's base URL (exported, § 17) and every client-side path guard. Throttles already key on
  scopes, not paths (§ 5), so they need no derivation.
- **No literal `"/api/"` in code outside the derivation module** — a ratchet scan over backend and frontend.
- **When a version is added**, the old prefix stays mounted as an alias for a declared window, answering with
  `Deprecation` and `Sunset` headers, and the ADR records the date the alias is removed.
- **External callback URLs are registered and frozen:** `registry.external_urls.register(name, path, reason,
  owner)`. They mount at their literal path under `API_ROOT`, regardless of `API_PREFIX`, and authenticate by
  signature, so they also appear in the public ledger.
- **A frozen path never changes.** A snapshot of `{name: path}` is committed; changing or removing an entry fails
  the test unless the snapshot is updated in the same reviewed change with a reason.

**Django + Next shape.** `core/urls_config.py` (derivation: `api_path(*parts)`, `api_root_path(*parts)`); root
`config/urls.py` iterates `registry.api_routes` under `API_PREFIX` and `registry.external_urls` under `API_ROOT`;
the cookie helpers in `users/` call `api_path("auth/refresh/")`.

**Enforced by.** `test_refresh_cookie_path_matches_the_refresh_route` · `test_no_literal_api_paths` (ratchet) ·
`test_external_urls_are_frozen` (snapshot) · `test_every_external_url_resolves_to_its_literal_path`.

**Configurable, not hard-coded.** `API_PREFIX`, `API_ROOT`; external URLs are registry data with a snapshot.

---

## 21. ⚠️ Conflicts with existing docs

These are recorded, not edited. Each names the file, the section and the fix.

| # | Existing doc says | Why it is a problem | Fix | Row |
|---|---|---|---|---|
| 1 | [`API_DESIGN.md`](API_DESIGN.md) § Machine callers — *"a machine caller is a principal with permissions, checked by the same RBAC layer"* | Underspecified in the way that matters: with whose permissions, bounded by what, and what stops a browser session satisfying a machine endpoint | Adopt § 9's recommendation (permission-code scopes, three gates, a machine-audience service role as the ceiling) and § 7's credential kinds; write the ADR before the first token endpoint | DB-21 |
| 2 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.4 step 1 — `CookieJWTAuthentication` *"fall back to `Authorization: Bearer` for machine callers"* | Machine tokens are opaque, prefixed, hashed and revocable (§ 8), not JWT access tokens; one class accepting both makes the credential-kind gate unenforceable and lets a copied access token act as a machine credential | Remove the fallback; machine tokens authenticate only through `ApiTokenAuthentication` (§ 7) | new |
| 3 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 11 — *"on 401: attempt ONE refresh"* — with no `authenticate_header()` specified for `CookieJWTAuthentication` | DRF turns `NotAuthenticated` into **403** when the first authenticator returns no `WWW-Authenticate` value, so the frontend never sees a 401 and never refreshes | Both authenticators implement `authenticate_header()` (§ 7); add `test_unauthenticated_is_401_with_www_authenticate` | new |
| 4 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12 — `REST_FRAMEWORK` has no renderer, parser, metadata, `URL_FORMAT_OVERRIDE` or `NON_FIELD_ERRORS_KEY` pins, and throttling uses DRF's default ident | DRF defaults serve the browsable HTML API, accept form-encoded bodies (a CSRF "simple request"), dump serializer metadata on `OPTIONS`, and key anonymous throttles on the whole raw `X-Forwarded-For` header | Add the pins of § 7; core throttles override `get_ident()` with `client_ip()` (§ 5) | new |
| 5 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12 — `DEFAULT_THROTTLE_RATES` as a literal dict in `settings.py` | A plugin needing a throttle scope must edit a protected file; unscoped views are silently unthrottled under `ScopedRateThrottle` | Scopes become `registry.throttle_scopes`; unscoped views get `default` (§ 5) | new |
| 6 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.1 — `max_page_size: ClassVar[int] = 100` on `BaseViewSet` | A literal the UI's page-size picker does not read; a picker offering more than the cap makes the pager and the rows disagree | Replace with `max(LIST_PAGE_SIZE_OPTIONS)`, exported to the frontend; move `filterset_fields`/`ordering_fields` into `ListSpec` (§ 1) | new |
| 7 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.2 — `CORS_ALLOW_HEADERS = [*default_headers, "x-csrf-token"]`, no `CORS_EXPOSE_HEADERS` | `Idempotency-Key` fails preflight; `Retry-After` and `X-Request-ID` are unreadable cross-origin | Add `idempotency-key` to allow-headers; expose `Retry-After`, `X-Request-ID` and the `RateLimit-*` headers | new |
| 8 | [`API_DESIGN.md`](API_DESIGN.md) § Lists — envelope `{count, next, previous, results}` | Not wrong; incomplete. Tables must parse URLs to render a pager, and nothing tells a client what was applied | Additive: `page`, `page_size`, `num_pages`, `meta` (§ 2) | — |
| 9 | [`API_DESIGN.md`](API_DESIGN.md) § Errors — envelope `{code, message, fields}` | Additive gaps: no `request_id`, no field paths for nested errors, no machine-readable field codes, no `retry_after_seconds`, and nothing routes Django-level errors (404 HTML, CSRF, oversize body) through it | Additive: § 3 | — |
| 10 | [`API_DESIGN.md`](API_DESIGN.md) § URLs — *"No `/v1/` for now"* | The decision is fine; hard-coded path literals make reversing it silently break cookies and client guards | Keep the decision; centralise `API_PREFIX`/`API_ROOT` now (§ 20) | DB-24 |
| 11 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2 — `PUBLIC_ROUTES` is a core-only dict | A plugin must edit core to add an anonymous endpoint | Registrable ledger (EXTENSIBILITY), asserted both ways (§ 15) | DB-22 |
| 12 | [`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md) § 7 — *"Raise DRF exceptions"* | Correct for views; wrong for services, which are also called from Celery and commands and must not import the HTTP layer | Services raise `core.exceptions.ServiceError`; the handler maps it (§ 3) | — |

---

## Pending decisions (for the repository owner)

1. **The token authorization model** (§ 9, **DB-21**). Recommended: permission-code scopes with a machine-owned
   service-role ceiling. The alternative worth considering is pure abilities (Design A) if the owner would rather
   keep machines entirely outside RBAC.
2. **Personal access tokens in core or not** (§ 9). Recommended: not in core; the model supports adding them.
3. **Read-only fields in input: `400` or silently ignored** (§ 12). Recommended `400`, consistent with
   API_DESIGN § Requests; the cost is clients that `PUT` a whole object back must drop read-only keys.
4. **The identity-provider exchange for acting users** (§ 10) — core, or a module that products with an IdP add.
5. **Default `FILE_SERVE_MODE`** for products without object storage — `x-accel` (recommended) needs the proxy
   configuration OPERATIONS specifies.
6. **Whether malware scanning is required by default for any core upload purpose** (§ 18). Recommended: optional
   in core; a product handling third-party documents sets it required.

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section. DRF behaviours cited (the `403` downgrade without
> `authenticate_header`, `get_ident()` returning the whole `X-Forwarded-For` header when `NUM_PROXIES` is unset,
> `Throttled` ceiling the wait, the default handler's `set_rollback()` covering only `APIException`) were checked
> against the installed `djangorestframework` 3.18.1 on that date; re-check after an upgrade.
