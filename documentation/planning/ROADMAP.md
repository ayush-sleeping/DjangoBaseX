# Roadmap

**Intent, not current state.** A row marked ⬜ is *not built* — check the code before assuming
otherwise. What exists today is described in [`../core/ARCHITECTURE.md`](../core/ARCHITECTURE.md).

Built by accumulation, one module at a time, tracking the
[Django-Nextjs-Journey](https://github.com/ayush-sleeping/Django-Nextjs-Journey) Level 2 plan.

---

## Status

| Capability | How it is built here | Status |
|------------|----------------------|--------|
| Health check | `/api/health/` | ✅ |
| API docs | drf-spectacular at `/api/docs/` | ✅ |
| Lint + format | Ruff | ✅ |
| AI agent guard rails | `AGENTS.md` contract + `.claude/` hooks, skills, subagents — [`AGENT_TOOLING.md`](../core/AGENT_TOOLING.md) | ✅ |
| Python types | mypy | ⬜ |
| Authentication | Cookie JWT — access/refresh, rotation, DB-backed sessions | ⬜ |
| Roles & permissions | Code-declared catalog + DRF permission classes + object-level scoping | ⬜ |
| Admin UI | Next.js dashboard — data tables, forms, ShadCN | ⬜ |
| Core CRUD modules | DRF viewsets + Next.js pages | ⬜ |
| Activity log | Append-only audit trail | ⬜ |
| Background jobs | Celery + Redis + Flower | ⬜ |
| Social login / 2FA | django-allauth + `pyotp` TOTP | ⬜ |
| Test suite | pytest + pytest-django + factory_boy | ⬜ |
| Containerisation | docker-compose — Django + Next + Postgres + Redis | 🔄 dev stack (both apps, SQLite) done |
| Configuration — nothing hard-coded | Boot refusal, typed settings registry, feature flags, lookups, locale/currency/timezone settings — [`CONFIGURATION.md`](../system-design/CONFIGURATION.md) | ⬜ |
| Extensibility | Full registry catalogue, soft-disable, versioned plugin SDK — [`EXTENSIBILITY.md`](../system-design/EXTENSIBILITY.md) | ⬜ |
| Observability | Request ids, JSON logs, one scrubber, three-rung health, metrics, error tracking — [`OBSERVABILITY.md`](../system-design/OBSERVABILITY.md) | ⬜ |
| Jobs & integrations | Job monitor, outbox, reconcilers, webhooks, safe HTTP, encrypted credentials — [`JOBS_AND_INTEGRATIONS.md`](../system-design/JOBS_AND_INTEGRATIONS.md) | ⬜ |
| Notifications & alerting | Purposes, channels, in-app store, ops alerting — [`NOTIFICATIONS_AND_ALERTING.md`](../system-design/NOTIFICATIONS_AND_ALERTING.md) | ⬜ |
| Data lifecycle | Audit engine, retention, soft delete, provenance, scoping — [`DATA_LIFECYCLE.md`](../system-design/DATA_LIFECYCLE.md) | ⬜ |
| Domain primitives | Money, sequences, state machines, bulk, import/export — [`DOMAIN_PRIMITIVES.md`](../system-design/DOMAIN_PRIMITIVES.md) | ⬜ |
| API platform | List pipeline, error catalogue, machine callers, contracts, files — [`API_PLATFORM.md`](../system-design/API_PLATFORM.md) | ⬜ |
| Frontend platform | Transport, data layer, module contract, nav-as-gate, tokens, i18n — [`FRONTEND_PLATFORM.md`](../system-design/FRONTEND_PLATFORM.md) | ⬜ |
| Operations | Setup, release images, rolling deploy, backups/restore — [`OPERATIONS.md`](../system-design/OPERATIONS.md) | ⬜ |
| Optional modules | Billing, approvals, documents, help centre, helpdesk, tenancy, search, AI — [`REUSABLE_MODULES.md`](../system-design/REUSABLE_MODULES.md) | ⬜ (plugins) |

The full capability map behind the rows above, with tiers, is [`PLATFORM_BLUEPRINT.md`](PLATFORM_BLUEPRINT.md).

---

## Decide before building

Two questions that get answered badly if they get answered by accident:

### 1. Session auth or JWT — not both ✅ decided

**Settled 2026-10-11 by [ADR-0009](../adr/0009-jwt-in-httponly-cookies.md):** JWT in `httpOnly`
cookies, backed by DB session rows, built to `AUTH_BLUEPRINT.md` Ch. 6 with `pyjwt` (not SimpleJWT).
`config/settings.py` still sets `SessionAuthentication` until `BUILD_ORDER` 1.1b replaces it with
`CookieJWTAuthentication`. No endpoint authenticates before then.

### 2. Tests before or after the first real feature

There are zero tests. Every module added before the suite exists is a module whose tests get written
later, or never — and "later" has a known success rate. Adding pytest + pytest-django is cheap now
and gets more expensive with every module.

**Recommendation: tests first.** The suite is a few hours of work at this size, and every feature
after it arrives covered.

---

## Suggested order

Dependency-ordered, not priority-ordered — each step is hard to do well before the one above it.

1. **pytest + pytest-django + factory_boy**, and a CI workflow that runs the `AGENTS.md` § 2 gate.
   Everything below is safer with this in place, and it is the cheapest it will ever be
2. ~~**Resolve DB-1** (auth model) and write the ADR~~ — ✅ ADR-0009
3. **Auth** — cookie JWT per ADR-0009 (`pyjwt`), `/me`, refresh rotation, and the frontend half in `src/lib/api.ts`
4. **RBAC** — groups, permission classes, object-level checks. Fail closed, like the DRF default
5. ~~**A custom `User` model**~~ — ✅ done 2026-10-11: `users.User`, email login
   ([ADR-0008](../adr/0008-custom-user-model-email-identity.md)), the project's first migration
6. **First CRUD module** (Users), backend and frontend, as the pattern every later module copies
7. **Type generation** from `/api/schema/` into the frontend (`TECH_DEBT` **DB-4**)
8. **Docker Compose** — Postgres + Redis, which unblocks realistic local development and CI
9. **Celery + Redis**, then the activity log, then 2FA/social login
10. **The platform services** — [`BUILD_ORDER.md`](BUILD_ORDER.md) Phases 5–9, in the order given there, before
    a second product is built on the core
