# Platform Blueprint

**The master map of everything a strong base must provide — every capability, which tier it belongs to, and
which document specifies it.** Start here when you ask *"what should DjangoBaseX have that it does not yet?"*

> **Intent, not current state.** Every row below marked ⬜ is **not built**. What exists today is described in
> [`../core/ARCHITECTURE.md`](../core/ARCHITECTURE.md) and [`ROADMAP.md`](ROADMAP.md). The sequence to build it in is
> [`BUILD_ORDER.md`](BUILD_ORDER.md) Phases 5–9.

---

## 0. Where this comes from, and why it exists

On **2026-09-29** the repository owner commissioned a study of several mature production codebases from different
domains — a plugin-based back office, a Django operations system, a multi-tenant self-service platform with
billing, and a reusable platform core. Between them they carry years of production incidents,
post-mortems and hard-won rules. The study produced roughly 450 findings. This document and the specifications it
links to are the distillation: **every mechanism worth having, argued on its own merits, with the failure it
prevents.** Per [`AGENTS.md`](../../AGENTS.md) rule 5a, the sources are deliberately not named anywhere in this
repository — only the mechanisms and the reasons.

The owner's brief, recorded because it is the tie-breaker for everything below:

> A big product — ERP, CRM, e-commerce, anything — needs a strong base with everything ready, so a team starts
> building on day one. It must be reliable and powerful, and **nothing may be hard-coded**. A product, not a college
> project.

That brief is now principle 7 of [`../VISION.md`](../VISION.md).

---

## 1. The twelve ideas that matter most

If you read nothing else, read these. Each one is something every studied codebase either got right late, got
wrong expensively, or never got at all.

| # | Idea | Why it is here | Spec |
|---|------|----------------|------|
| 1 | **Every list the core keeps is a registry.** Nav, permissions, roles, public routes, jobs, webhook events, API abilities, retention policies, recyclable types, search sources, health probes, settings, flags — if core holds a literal that names a model, path, event or ability, the next product's first move is a core edit | One studied platform needed ~20 core edits to add or remove a single plugin | [`EXTENSIBILITY.md`](../system-design/EXTENSIBILITY.md) |
| 2 | **Nothing hard-coded, few knobs.** Deployment, tenant and business *facts* (hosts, currency, timezone, locale, brand, thresholds, vocabularies, credentials) live in env, the typed settings registry or lookup tables — never in code. *Behavioural* switches stay few and must pass an admission test | Hundreds of hard-coded currency and timezone literals turned "support a second market" into a grep project in two of the studied codebases | [`CONFIGURATION.md`](../system-design/CONFIGURATION.md) |
| 3 | **Refuse to boot when unsafe.** Production refuses to start with a placeholder secret, a reused key, `DEBUG`, a console mail backend or an unknown environment name — at settings import, not only in a system check, and reporting every problem at once | System checks do not run when gunicorn serves the app; case-sensitive `== "production"` checks were bypassed by `Production` and `staging` | [`CONFIGURATION.md`](../system-design/CONFIGURATION.md) |
| 4 | **Fail closed, and say which way every default fails.** Unknown flag = off; scoping that finds no rule returns nothing, never everything; a missing settings row resolves to the *safe* value; an unregistered credential probe reports *unverifiable*, never *verified* | "Admin bypass returns `None`" became an unscoped query that showed every tenant's data | [`BUG_CLASSES.md`](../system-design/BUG_CLASSES.md) |
| 5 | **Zero is not a fact.** Every figure carries its state — `live · quiet · never · off`. An unmonitored surface reads *untracked*, never `0`; "no failed jobs" is not "healthy" | A queue sat unprocessed for months with an empty failed-jobs table, which read as healthy | [`OBSERVABILITY.md`](../system-design/OBSERVABILITY.md) |
| 6 | **Durable work goes through an outbox; every transient state has a reconciler.** Same-transaction enqueue, unique dedupe key, leased claims, an `unknown` state for ambiguous sends, and a beat-scheduled reconciler for anything left `PENDING` | Lost webhooks, double-sent emails and resources stuck in `PENDING` forever | [`JOBS_AND_INTEGRATIONS.md`](../system-design/JOBS_AND_INTEGRATIONS.md) |
| 7 | **One way to do each thing, enforced by a test that can fail.** One transport, one list pipeline, one error envelope, one ledger entrypoint, one audit writer — each guarded by a source-scan test with a ratchet allow-list that may only shrink | Twelve code paths each wrote a wallet balance by hand; three error envelopes forced clients to carry three parsers | [`ENGINEERING_PRACTICES.md`](../system-design/ENGINEERING_PRACTICES.md) |
| 8 | **A guard that does not run is documentation.** CI on every push, seeding before tests, parity tests that fail rather than skip, completeness tests that fail on an empty universe, and a smoke check that each tool actually runs | Two of the studied codebases had CI written and never switched on; a third had none by decision | [`ENGINEERING_PRACTICES.md`](../system-design/ENGINEERING_PRACTICES.md) |
| 9 | **The frontend's load state is a contract.** Error is disjoint from empty, cache keys carry the tenant, a failed refetch keeps the last good data | 145 of 201 pages in one codebase rendered a failed fetch as "No invoices yet" | [`FRONTEND_PLATFORM.md`](../system-design/FRONTEND_PLATFORM.md) |
| 10 | **Money and numbering are primitives, not features.** Decimal + currency always paired, one rounding rule, one quantisation point; gapless document sequences locked inside the caller's transaction | Floats in money request schemas; two callers minting the same invoice number on a fresh install | [`DOMAIN_PRIMITIVES.md`](../system-design/DOMAIN_PRIMITIVES.md) |
| 11 | **Deploys are boring by construction.** Immutable tagged images, env validated inside the new image, a verified backup that aborts the deploy on failure, migrate from the new image before the swap, one-at-a-time rolling swap gated on readiness, expand/contract enforced by a linter | Containers started before migrations gave a minute of 500s twice in a day; a scale-down recreated the surviving container for ~25 s of 502s | [`OPERATIONS.md`](../system-design/OPERATIONS.md) |
| 12 | **The audit trail answers "who, what, from where, and what changed".** Field diffs with secrets masked, CLI/job provenance, impersonation stamped on every row, structurally read-only, retention opt-in | "Who granted this user Admin, and when?" was unanswerable in one codebase | [`DATA_LIFECYCLE.md`](../system-design/DATA_LIFECYCLE.md) |

---

## 2. Tiers

Every capability carries exactly one tier. The tier decides *where* it lives and *when* it is built.

| Tier | Means | Lives in | Built |
|------|-------|----------|-------|
| **Tier 1 · Core** | Every product needs it, and retrofitting it is expensive | `backend/core/`, `frontend/src/core/` | With, or immediately after, Phases 1–2 |
| **Tier 2 · Core** | Every product needs it, but it can land after auth/RBAC without rework | core | Before the second product (Phase 10) |
| **Tier 3 · Module** | Some products need it — a reusable plugin, not core | its own plugin repo | When the first product that needs it arrives |
| **Process** | A practice, gate or document convention | docs, CI, `AGENTS.md` | As soon as the thing it governs exists |

⚠️ **The VISION test still applies to every row:** *"Would the next product want this?"* If only some products do,
it is Tier 3 — however useful it is.

---

## 3. The capability catalogue

Status key: ⬜ not built · 🟡 partly specified elsewhere already · ✅ built. Specifications live in
`documentation/system-design/`; follow the link in each section heading.

### 3.1 Extensibility — [`EXTENSIBILITY.md`](../system-design/EXTENSIBILITY.md)

| Capability | Tier | Status |
|------------|------|--------|
| Three-tier app taxonomy (platform · kernel · plugin) with a declared layer per app and a sanctioned-FK rule | 1 | ⬜ |
| The full registry catalogue with one uniform contribution shape (key · owner · permission · flag · order · component · props) | 1 | 🟡 `CORE_ARCHITECTURE_PLAN.md` § 2 lists eight |
| Registration rules: `ready()` only, one-way, duplicates raise, DB values as callables, no DB access in `ready()`, lazy seal | 1 | 🟡 |
| Every registry documents its unknown-key default, chosen in the safe direction | 1 | ⬜ |
| Plugin discovery without importing; absent-vs-broken import distinguished by `ModuleNotFoundError.name` | 1 | ⚠️ conflicts with `AUTH_BLUEPRINT.md` § 7.2 — see § 5 |
| Soft-disable contract: one switch per plugin gates every surface | 2 | ⬜ |
| Versioned SDK facade as the only plugin import surface; `capabilities()`; compatibility checks | 2 | ⬜ |
| Service-contract registry (named, single provider) and a failure-isolated event bus | 2 | 🟡 |
| UI contribution slots resolved by a generated frontend component registry | 2 | ⬜ |
| Boundary tests beyond imports: vocabulary AST scan, core FKs target core, core-only assembly, frontend route strings, icon keys | 1 | 🟡 |
| Plugin scaffolder whose output equals a checked-in reference plugin | 2 | 🟡 `BUILD_ORDER` 3.3 |

### 3.2 Configuration — [`CONFIGURATION.md`](../system-design/CONFIGURATION.md)

| Capability | Tier | Status |
|------------|------|--------|
| The configuration ladder: which kind of value lives where (constant · env · setting · flag · lookup · credential · identity row) | 1 | ⬜ |
| Import-time production refusal, reporting every problem at once; CI step proving it refuses | 1 | 🟡 `TECH_DEBT` DB-7 |
| `APP_ENV` fail-closed: unknown means production, one predicate everywhere, loud ribbon | 1 | ⬜ |
| Env schema validator (unknown / missing / undocumented keys) run inside the release image | 2 | ⬜ |
| Project identity: one name, slug and domain derive issuer, from-address, cookie names, API title | 1 | ⬜ |
| Typed settings registry: declared in code, never reset on reseed, strict coercion, scope cascade user → tenant → platform → default, audited, cached with version bump | 1 | 🟡 `AUTH_BLUEPRINT.md` § 3.13 |
| The settings admission test, and "a setting nothing reads is a defect" enforced by a test | Process | ⬜ |
| Feature flags with kill-switch-first resolution, owner, expiry; ship dark by default | 1 | ⬜ |
| Guard modes `off · log_only · enforce`, with a test that shipping a guard changes nothing | 2 | ⬜ |
| Admin-editable vocabularies: stable key + editable label, membership validated from the table | 1 | ⬜ |
| Locale, currency, timezone and formats as platform / tenant / user settings; UTC storage; ISO-8601 API | 1 | ⬜ |
| Runtime config in the DB with env only as prefill (e.g. storage backend resolved per operation) | 2 | ⬜ |
| Anti-hard-coding scans: currency/timezone literals, role-name literals, secret env reads outside settings | 1 | ⬜ |

### 3.3 Identity and access — already specified

These are **already specified in depth** and the study mostly confirmed them. Read the existing documents; the
study's additions are folded into the specs named in the right-hand column.

| Area | Existing spec | Additions from the study live in |
|------|---------------|-----------------------------------|
| Authentication, sessions, MFA, re-auth | [`AUTH_BLUEPRINT.md`](../system-design/AUTH_BLUEPRINT.md) | `FRONTEND_PLATFORM.md` (session marker cookie, re-auth modal) · `BUG_CLASSES.md` (N login paths) |
| RBAC, permissions, roles | [`RBAC_DESIGN.md`](../system-design/RBAC_DESIGN.md) | `EXTENSIBILITY.md` (role and default-role registries, additive grants) · `API_PLATFORM.md` (reverse index "what does this permission open") |
| Object scoping | [`DATA_MODEL.md`](../system-design/DATA_MODEL.md) § 5 | `DATA_LIFECYCLE.md` (write-path narrowing, registered scopes, `None` vs empty) |
| Failure catalogue | [`AUTH_FAILURE_MODES.md`](../system-design/AUTH_FAILURE_MODES.md) | `BUG_CLASSES.md` (the cross-cutting register) |

### 3.4 Data lifecycle — [`DATA_LIFECYCLE.md`](../system-design/DATA_LIFECYCLE.md)

| Capability | Tier | Status |
|------------|------|--------|
| One base model set: UUID pk, timestamps, actor columns from a contextvar, optional optimistic locking | 1 | 🟡 `DATA_MODEL.md` § 2 |
| Activity/audit engine: field diffs, masked secrets, source/via/CLI provenance, impersonation stamp, batch id, read-only, streamed export | 1 | 🟡 `AUTH_BLUEPRINT.md` § 3.12 |
| State-transition history written for every write path; never durations from `updated_at` | 2 | ⬜ |
| Retention engine: age **and** row caps, batched, opt-in for evidence tables, `--status`/`--dry-run`, floors | 2 | 🟡 `auth_cleanup` only |
| Soft delete with Postgres partial unique constraints; recycle bin from an allow-listed registry | 2 | 🟡 `DATA_MODEL.md` D4 |
| Provenance: `created_via` from the principal, `source_ref` as a pointer, null means unknown | 2 | ⬜ |
| Invariants in `clean()` **and** a DB constraint, with a test that the DB rejects a bypass | 1 | ⬜ |
| Object scoping extensions: every listable model registered, write-path narrowing, tenant safety net | 1 | 🟡 |
| Delegation grants (view/manage per module, independent of the org chart) | 3 | ⬜ |

### 3.5 Domain primitives — [`DOMAIN_PRIMITIVES.md`](../system-design/DOMAIN_PRIMITIVES.md)

| Capability | Tier | Status |
|------------|------|--------|
| Money: Decimal + currency, one quantisation helper, one rounding rule, floats banned by a scan | 1 | ⬜ |
| Document number sequences: per series/scope/period, peek vs reserve, configurable format and reset | 2 | ⬜ |
| State-machine helper with `allowed_transitions` in responses | 2 | ⬜ |
| Business calendar (working hours, holidays, timezone) | 2 | ⬜ |
| Bulk actions that re-run the list's own pipeline and report what they skipped | 2 | ⬜ |
| Import/export registry with natural-key upsert, FK remap and diff audit | 2 | ⬜ |
| Open-findings queue — the place drift, dead deliveries and give-ups land for a human | 2 | ⬜ |
| PDF rendering primitive (autoescape, no-network fetcher, rendered in a job) | 3 | ⬜ |
| Generation-counter caching; never cache a failed lookup | 2 | ⬜ |

### 3.6 API platform — [`API_PLATFORM.md`](../system-design/API_PLATFORM.md)

| Capability | Tier | Status |
|------------|------|--------|
| One list pipeline: allow-listed sort with fallback, required pk tiebreak, page cap = the UI's largest option, unknown filters rejected | 1 | 🟡 `API_DESIGN.md` |
| One error envelope for *everything*, with a code catalogue exported to the frontend | 1 | 🟡 |
| Rate limiting: shared store, scope per view, `retry_after_seconds`, per-recipient throttles for anonymous email/SMS | 1 | 🟡 |
| Machine callers: system-named consumers, prefixed hashed tokens, abilities validated at write, request log | 2 | ⚠️ decision needed — see § 5 |
| Contract generation with three drift checks; enums and permission codes exported to the frontend | 1 | 🟡 `TECH_DEBT` DB-4 |
| OpenAPI quality tests: every operation publishes the permission it requires | 2 | ⬜ |
| Files: content-sniffed uploads, private files via an authenticated view, per-purpose policy registry | 1 | ⬜ |
| Never-expose floor and registry-driven read API with field allow-lists | 3 | ⬜ |

### 3.7 Jobs and integrations — [`JOBS_AND_INTEGRATIONS.md`](../system-design/JOBS_AND_INTEGRATIONS.md)

| Capability | Tier | Status |
|------------|------|--------|
| Job registry → beat schedules synced in `post_migrate`; queue invariants as tests | 1 | 🟡 `jobs` registry |
| Job-run monitor: `never_run · failing · overdue · ok` and "worker seen recently" | 1 | ⬜ |
| Transactional outbox with leases and an `unknown` state | 1 | ⬜ |
| Reconciler base class; single-flight locks with short TTLs | 2 | ⬜ |
| Outbound webhooks: signed timestamp, SSRF guard at write **and** send, breaker, delivery log, redeliver | 2 | 🟡 models listed in `DATA_MODEL.md` |
| Inbound webhook verification with DB idempotency | 2 | ⬜ |
| SSRF-safe HTTP client factory; provider error mapping (upstream 401/403 → 502) | 1 | ⬜ |
| Encryption service with a MultiFernet key list separate from `SECRET_KEY`; startup self-test | 1 | 🟡 MFA key only |
| Schema-driven encrypted integration credentials with save-time probes and audited reveal | 2 | ⬜ |
| Integration registry with usage probes and an explicit *untracked* state | 2 | ⬜ |
| Non-production outbound guard: HTTP allow-list answering 423, mail redirected to one test recipient | 1 | ⬜ |

### 3.8 Notifications and alerting — [`NOTIFICATIONS_AND_ALERTING.md`](../system-design/NOTIFICATIONS_AND_ALERTING.md)

| Capability | Tier | Status |
|------------|------|--------|
| Notification purposes registry; callers never carry a destination; channel adapters | 2 | 🟡 `Notification` model only |
| Event × channel matrix seeded from code, per-user preferences, preview, send-test, test routing | 2 | ⬜ |
| In-app store: per-user read, shared resolve, digest upsert | 2 | ⬜ |
| Ops alerting people don't mute: one dispatcher, DB ledger, incidents, quiet hours, digests | 2 | ⬜ |

### 3.9 Observability — [`OBSERVABILITY.md`](../system-design/OBSERVABILITY.md)

| Capability | Tier | Status |
|------------|------|--------|
| Request id end to end (validated, contextvar, into Celery, forwarded by Next) | 1 | 🟡 `TECH_DEBT` DB-9 |
| Structured JSON logs; one scrubber shared by logs, Sentry and the frontend | 1 | 🟡 DB-9 |
| Health in three rungs; data-plane self-checks for required rows | 1 | 🟡 DB-11 |
| Metrics with closed, pre-initialised label sets; alert rules that watch themselves | 2 | ⬜ |
| Error tracking (Sentry, or built-in fingerprinted groups) | 2 | ⬜ |
| System Health page; the "zero is not a fact" state model; `manage.py doctor` umbrella | 2 | ⬜ |

### 3.10 Frontend platform — [`FRONTEND_PLATFORM.md`](../system-design/FRONTEND_PLATFORM.md)

| Capability | Tier | Status |
|------------|------|--------|
| One transport with a typed error taxonomy; `fetch` banned elsewhere by lint | 1 | 🟡 `NEXTJS_STANDARDS.md` |
| One data/cache layer; the load-state contract; URL-backed list state | 1 | ⬜ |
| Module UI contract (Index · Form · Show) and a standard DataTable | 1 | ⬜ |
| Server-built navigation that is also the route gate, default-deny | 1 | ⬜ |
| Fail-closed permission provider fed by one bootstrap endpoint | 1 | 🟡 `/me` |
| Session marker cookie so the edge guard can tell "needs refresh" from "signed out" | 1 | ⚠️ conflicts with `AUTH_BLUEPRINT.md` cookie paths — see § 5 |
| Design tokens with foreground pairs, dark mode, token-completeness test | 1 | ⬜ |
| Runtime branding with a validated colour grammar and a contrast solver | 2 | ⬜ |
| Per-request CSP nonce, Report-Only first, enforcement flipped at runtime | 2 | ⬜ |
| i18n from day one; formatters from bootstrap locale/currency/timezone | 1 | ⬜ |

### 3.11 Operations — [`OPERATIONS.md`](../system-design/OPERATIONS.md)

| Capability | Tier | Status |
|------------|------|--------|
| One-command setup: free ports persisted, URL-safe secrets, idempotent, health-polled | 1 | 🟡 `BUILD_ORDER` 4.1 |
| First-run setup wizard behind a one-time token with real connectivity tests | 2 | ⬜ |
| Immutable release images; deploy driver with verified backup, migrate-first and rolling swap | 2 | ⬜ |
| Expand/contract migrations enforced by a linter; `migrations_doctor` before deploy | 1 | 🟡 `DATABASE_MIGRATIONS.md` |
| Restore that keeps the target's own connections (`config_snapshot`) | 2 | ⬜ |
| PgBouncer-safe database settings; proxy and container hygiene; infrastructure policy tests | 2 | ⬜ |

### 3.12 Engineering practice — [`ENGINEERING_PRACTICES.md`](../system-design/ENGINEERING_PRACTICES.md), [`BUG_CLASSES.md`](../system-design/BUG_CLASSES.md), [`LESSONS_LEARNED.md`](../system-design/LESSONS_LEARNED.md)

| Capability | Tier | Status |
|------------|------|--------|
| Tests that can fail; architecture tests with shrinking ratchets; completeness tests that fail on an empty universe | Process | 🟡 `TESTING_STRATEGY.md` |
| CI that runs on every push, seeds before testing, and proves each tool runs | Process | 🟡 `BUILD_ORDER` 2.3 |
| Recurring bug-class register as the review checklist | Process | ⬜ |
| ADR template with Invariant, Where it bites, Decided by, Enforced by | Process | 🟡 |
| Generated folder indexes and a doc link test | Process | ⬜ |
| Platform semver, CHANGELOG with upgrade notes, rehearsed upgrade channel | Process | 🟡 `UPGRADING.md` |
| AI-assisted workflow: specs with failure modes, the diff is the verdict, worktree per lane | Process | 🟡 `AGENTS.md` § 5 |

### 3.13 Optional modules — [`REUSABLE_MODULES.md`](../system-design/REUSABLE_MODULES.md)

All **Tier 3**. Each is a plugin a product adds when it needs it; none belongs in core.

| Module | Wanted by |
|--------|-----------|
| Billing, ledger and payments (buckets + append-only ledger, metering, invoicing, pluggable tax, gateways, dunning) | SaaS, e-commerce, ERP |
| Approvals / maker-checker | ERP, finance, admin-heavy products |
| Templated documents (quotes, delivery notes, certificates) | ERP, CRM |
| Data ingestion / sync framework with a human review queue | Anything with integrations |
| Alert rules engine · Automation engine | Operations-heavy products |
| Knowledge base / in-app help centre | Every product with non-technical users |
| Helpdesk with business-hours SLAs | CRM, SaaS |
| Organisations, tenancy and white-label | B2B SaaS, reseller platforms — ⚠️ see § 5 on whether part of this is core |
| Global search · AI assistant · Feedback widget | Most products |

---

## 4. Principles the specs share

These run through every document above; they are stated once here so a reader can check a design against them.

1. **Mechanism over convention.** A rule that only lives in prose is already half-broken. Each spec names the
   test, system check or CI step that enforces it — and says so honestly when nothing does yet.
2. **Fail closed, visibly.** Refusals are distinct from empty results; "not measured" is distinct from zero;
   "not configured" is distinct from "off".
3. **One writer per invariant.** Ledgers, audit rows, grants and settings each have exactly one mutation function,
   and a source scan proves nobody else writes.
4. **Record, don't infer.** Status history, provenance and actors are written when they happen — never
   reconstructed later from `updated_at` or guessed from "whoever is logged in".
5. **Derive lists from the code.** Browser-check page lists, docs coverage, help coverage, queue topology and
   completeness tests all read the registries. A hand-kept list rots.
6. **Honest documentation.** Every spec opens with a *Blueprint* banner and closes with *Pending decisions* and
   *Doc accuracy*. A doc describing code that does not exist is a defect.

---

## 5. ⚠️ Contradictions with existing documents — resolve before building

The study found places where DjangoBaseX's own documents specify something a studied codebase learned the hard way
is wrong — or found an outright defect. Each is now a [`TECH_DEBT.md`](TECH_DEBT.md) row so it cannot be lost.

| # | Existing doc says | The lesson | Recommended resolution | Row |
|---|-------------------|------------|------------------------|-----|
| 1 | `AUTH_BLUEPRINT.md` § 7.2 — a plugin that fails to import has "only `ImportError` swallowed" | A typo *inside* a present plugin also raises `ModuleNotFoundError`, so the plugin silently vanishes and the only symptoms are missing permissions and 404s | Catch `ModuleNotFoundError` only when `exc.name` is the plugin's own package; re-raise everything else | DB-18 |
| 2 | `dbx.E005`–`E008` production-safety rules are Django system checks | System checks do not run when gunicorn/uvicorn serves the app | Keep the checks for `check --deploy`, **and** run the same audit at the end of settings import, raising `ImproperlyConfigured` | DB-19 |
| 3 | `AUTH_BLUEPRINT.md` § 6.1 — access cookie `Path=/api/`, refresh cookie `Path=/api/auth/refresh/` | No auth cookie reaches a page navigation, so any Next.js edge route guard bounces every signed-in user once the access token expires — a studied codebase shipped exactly this as "logged out every hour" | Add a `Path=/` httpOnly **session marker** cookie (no credential inside), set and cleared with the session | DB-20 |
| 4 | `API_DESIGN.md` § Machine callers — machines are principals with permissions checked by the same RBAC layer | One studied design gives machines *abilities* and makes permission checks always false for them; another makes scopes *equal* RBAC permission strings with two gates (credential scope **and** the owner's live permission) | Owner decision — see `API_PLATFORM.md`. Either is defensible; mixing them is not | DB-21 |
| 5 | `AUTH_BLUEPRINT.md` § 9.2 — `PUBLIC_ROUTES` is a core-only dict | A plugin then has to edit core to add its anonymous surface, or scatter `AllowAny` | Make it `registry.public_routes`; `dbx.E007` and the route test read the union | DB-22 |
| 6 | `DATA_MODEL.md` D3 recommends no organisation model in core | One studied core concluded the core must own the tenant table (status vocabulary gates auth); retrofitting tenancy was measured at 258 function signatures | Owner decision — record the measured retrofit cost in the D3 ADR either way | DB-23 |
| 7 | `API_DESIGN.md` — no `/v1/` until the first external consumer | Moving the prefix later silently broke a refresh-cookie path, a rate-limit tier table and an interceptor's own URL guards | Keep the decision if wanted, but centralise `API_PREFIX` and derive every path from it now | DB-24 |
| 8 | `AUTH_BLUEPRINT.md` § 17.5 — `__Host-` on the access cookie | `__Host-` requires `Path=/`; the access cookie is `Path=/api/`, so the browser rejects it | `__Secure-` for path-scoped cookies, `__Host-` only for `Path=/` ones — decide with row 3 | DB-26 |
| 9 | `README.md`, `NEW_PROJECT.md`, `ONBOARDING.md` — `SECRET_KEY` from `get_random_secret_key()` | A key starting with `$` is read by django-environ as a reference to another variable | Generate with `secrets.token_urlsafe(50)` | DB-25 |
| 10 | `config/settings.py` (**live code**) — `AnonRateThrottle` with DRF `NUM_PROXIES` unset | DRF then keys the throttle on the whole client-supplied `X-Forwarded-For`, so the limit is bypassable by rotating the header | Set `NUM_PROXIES` from `TRUSTED_PROXY_COUNT` or route identity through `client_ip()`; pin renderer and parser classes | DB-30 |
| 11 | `AUTH_BLUEPRINT.md` § 11 — the client refreshes on 401 | DRF answers 403, not 401, when the authenticator has no `authenticate_header()` | Specify `authenticate_header()` on the cookie authenticator; test anonymous → 401 | DB-31 |

---

## 6. Pending decisions for the repository owner

Beyond § 5, the specs raise these. None blocks Phases 1–2.

1. **One frontend data layer** — TanStack Query (recommended) or RTK Query. `FRONTEND_PLATFORM.md`.
2. **Built-in error tracking or Sentry-only.** `OBSERVABILITY.md`.
3. **Celery from day one, or an in-process worker first** (the monitor design works for both). `JOBS_AND_INTEGRATIONS.md`.
4. **Where plugin documentation lives** — in each plugin repo, or all in core. `ENGINEERING_PRACTICES.md`.
5. **Release versioning** — SemVer (recommended for a platform) or CalVer tags. `OPERATIONS.md`.

---

## 7. How to use this document

- **Proposing a feature for DjangoBaseX?** Find its row. If it has one, read the linked spec first. If it has none,
  apply the VISION test and the tier table in § 2 before writing anything.
- **Building one?** Take the task from [`BUILD_ORDER.md`](BUILD_ORDER.md), build to the spec, then flip the row
  here to ✅ and move the "how it works" into `documentation/core/`.
- **Found a spec that is wrong?** Fix it in the same change as the code that proved it wrong, and note it in
  [`../DAILY_CHANGES.md`](../DAILY_CHANGES.md).
