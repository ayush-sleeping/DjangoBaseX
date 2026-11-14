# Roadmap

> **Status:** Planning summary — checked 2026-11-14 · row statuses mirror the ✅/⬜ marks in [`BUILD_ORDER.md`](BUILD_ORDER.md), which is the source of truth; phases 0–8 are built except 7.4–7.8 and 8.5.

**Intent, not current state.** A row marked ⬜ is *not built* — check the code before assuming
otherwise. What exists today is described in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and
[`../core/ARCHITECTURE.md`](../core/ARCHITECTURE.md).

Built by accumulation, one module at a time.

---

## Status

| Capability | How it is built here | Status |
|------------|----------------------|--------|
| Health check | `/api/health/` | ✅ |
| API docs | drf-spectacular at `/api/docs/` | ✅ |
| Lint + format | Ruff | ✅ |
| AI agent guard rails | `AGENTS.md` contract + `.claude/` hooks, skills, subagents — [`AGENT_TOOLING.md`](../core/AGENT_TOOLING.md) | ✅ |
| Python types | mypy | ⬜ |
| Authentication | Cookie JWT — access/refresh, rotation, DB-backed sessions | ✅ [ADR-0009](../adr/0009-jwt-in-httponly-cookies.md), BUILD_ORDER 1.1 |
| Roles & permissions | Code-declared catalog + the `core/api/` gate + object-level scoping | ✅ `rbac/`, the `core/api/` gate, `visible_to()` (1.2–1.4) |
| Admin UI | Next.js dashboard — data tables, forms, ShadCN | 🔄 app shell and design system (8.3), Users screens (1.5); nonce CSP and runtime brand colours (8.5); security headers, logos, host identity ⬜ (8.5b) |
| Core CRUD modules | DRF viewsets + Next.js pages | 🔄 the Users module (1.5); `examples/plugins/notes` |
| Activity log | Append-only audit trail | ✅ audit engine (6.4) |
| Background jobs | Celery + Redis + Flower | ✅ Celery + beat from the job registry (7.1, [ADR-0012](../adr/0012-celery-from-day-one.md)); Flower not |
| Social login / 2FA | django-allauth + `pyotp` TOTP | 🔄 TOTP 2FA done (1.1d); social login not |
| Test suite | pytest + pytest-django + factory_boy | ✅ backend (2.1–2.3, CI on PostgreSQL); frontend Vitest + MSW (8.1); no browser end-to-end tests |
| Containerisation | docker-compose — Django + Next + Postgres + Redis | 🔄 dev stack (both apps, PostgreSQL 16, Redis, Celery worker) done (4.4); production Docker not |
| Configuration — nothing hard-coded | Boot refusal, typed settings registry, feature flags, lookups, locale/currency/timezone settings — [`CONFIGURATION.md`](../system-design/CONFIGURATION.md) | ✅ boot refusal (5.1), settings registry (5.3), flags (5.4), lookups and locale (5.5), anti-hard-coding scans (5.6) |
| Extensibility | Full registry catalogue, soft-disable, versioned plugin SDK — [`EXTENSIBILITY.md`](../system-design/EXTENSIBILITY.md) | 🔄 registries, plugin discovery, scaffold, frontend mounting and an example (Phase 3); full catalogue, soft-disable and the SDK not (9.1) |
| Observability | Request ids, JSON logs, one scrubber, three-rung health, metrics, error tracking — [`OBSERVABILITY.md`](../system-design/OBSERVABILITY.md) | ✅ request ids, logs, scrubber, health rungs (6.1, 6.2) |
| Jobs & integrations | Job monitor, outbox, reconcilers, webhooks, safe HTTP, encrypted credentials — [`JOBS_AND_INTEGRATIONS.md`](../system-design/JOBS_AND_INTEGRATIONS.md) | 🔄 job monitor, outbox, reconcilers (7.1–7.3), safe HTTP + non-production guard (7.4), encryption service (6.3), webhooks outbound + inbound (7.6) |
| Notifications & alerting | Purposes, channels, in-app store, ops alerting — [`NOTIFICATIONS_AND_ALERTING.md`](../system-design/NOTIFICATIONS_AND_ALERTING.md) | ⬜ |
| Data lifecycle | Audit engine, retention, soft delete, provenance, scoping — [`DATA_LIFECYCLE.md`](../system-design/DATA_LIFECYCLE.md) | 🔄 audit engine (6.4); retention engine (7.5); rest ⬜ (9.3) |
| Domain primitives | Money, sequences, state machines, bulk, import/export — [`DOMAIN_PRIMITIVES.md`](../system-design/DOMAIN_PRIMITIVES.md) | 🔄 money (6.5); rest ⬜ (9.4) |
| API platform | List pipeline, error catalogue, machine callers, contracts, files — [`API_PLATFORM.md`](../system-design/API_PLATFORM.md) | 🔄 typed errors and contract generation (8.1, 8.4); rest ⬜ (9.2) |
| Frontend platform | Transport, data layer, module contract, nav-as-gate, tokens, i18n — [`FRONTEND_PLATFORM.md`](../system-design/FRONTEND_PLATFORM.md) | ✅ transport, data layer, nav-as-gate, design system, i18n (8.1–8.4); CSP and branding ⬜ (8.5) |
| Operations | Setup, release images, rolling deploy, backups/restore — [`OPERATIONS.md`](../system-design/OPERATIONS.md) | 🔄 setup (4.1), doctor (4.2, 7.2); release images, deploy, backups ⬜ (9.5) |
| Optional modules | Billing, approvals, documents, help centre, helpdesk, tenancy, search, AI — [`REUSABLE_MODULES.md`](../system-design/REUSABLE_MODULES.md) | ⬜ (plugins) |

The full capability map behind the rows above, with tiers, is [`PLATFORM_BLUEPRINT.md`](PLATFORM_BLUEPRINT.md).

---

## Decide before building

Two questions that get answered badly if they get answered by accident:

### 1. Session auth or JWT — not both ✅ decided

**Settled 2026-10-11 by [ADR-0009](../adr/0009-jwt-in-httponly-cookies.md):** JWT in `httpOnly`
cookies, backed by DB session rows, built to `AUTH_BLUEPRINT.md` Ch. 6 with `pyjwt` (not SimpleJWT).
`CookieJWTAuthentication` is the default authentication class and `core.permissions.DefaultDeny` the default permission class (`config/settings.py`, `REST_FRAMEWORK`).

### 2. Tests before or after the first real feature ✅ tests first

**Settled 2026-10-11:** pytest landed (`BUILD_ORDER` 2.1) before any auth code. Kept for the
reasoning: there were zero tests. Every module added before the suite exists is a module whose tests get written
later, or never — and "later" has a known success rate. Adding pytest + pytest-django is cheap now
and gets more expensive with every module.

---

## Order

The build order is [`BUILD_ORDER.md`](BUILD_ORDER.md) — numbered tasks in dependency order with ✅/⬜ marks. Do not keep a second list here.
