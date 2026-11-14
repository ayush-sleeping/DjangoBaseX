# Architecture

> **Status:** Detail companion — checked 2026-11-14 · describes what is built: auth, RBAC, Users module, settings/flags/lookups, audit log, Celery worker + beat, health rungs. Not built: see [§ What does not exist yet](#what-does-not-exist-yet).

**How the two halves fit together.** This file describes what **exists**. Anything planned is marked 🔜
and lives in [`../planning/ROADMAP.md`](../planning/ROADMAP.md) and `BUILD_ORDER.md`. The one-screen hub is
[`../ARCHITECTURE.md`](../ARCHITECTURE.md); purpose and hard rules are [`../PURPOSE.md`](../PURPOSE.md) and
[`../INVARIANTS.md`](../INVARIANTS.md); recurring failures are in
[`../system-design/TRAPS.md`](../system-design/TRAPS.md).

---

## The shape

```
Browser
   │
   │  http://localhost:3000
   ▼
┌──────────────────────────────┐
│  Next.js 16 (App Router)     │   frontend/
│  React 19 · Tailwind 4 · TS  │
│                              │
│  src/app/      routes        │
│  src/core/lib/api.ts  ← the ONLY  │
│                  place that  │
│                  talks HTTP  │
└──────────────┬───────────────┘
               │  NEXT_PUBLIC_API_URL
               │  http://localhost:8000
               ▼
┌──────────────────────────────┐
│  Django 5.2 + DRF            │   backend/
│                              │
│  config/    settings · urls  │
│  core/ users/ rbac/          │
│  project/ plugins/ (optional)│
└───────┬──────────────┬───────┘
        ▼              ▼
  PostgreSQL 16     Redis (cache, Celery broker)
  (Compose, CI;     ▲
  SQLite on bare    │
  runserver)   Celery worker (+ beat, `scheduler` profile)
```

Two processes, two toolchains, one HTTP boundary. They are deployable independently, and that is the
point of [ADR-0002](../adr/0002-api-first-drf-not-django-templates.md).

---

## Backend

### Layout

| Path | Holds |
|------|-------|
| `backend/config/` | The Django project package — `settings.py`, `urls.py`, `asgi.py`, `wsgi.py` |
| `backend/core/` | Platform app: registry, settings/flags/lookups, audit log, jobs and outbox, health, the `core.api` view gate |
| `backend/users/`, `backend/rbac/` | Platform apps: identity, auth, sessions, invitations, MFA; roles and permission catalog ([ADR-0010](../adr/0010-platform-layer-is-logical.md)) |
| `backend/project/`, `backend/plugins/` | A product's own code and plugins, loaded only when present; `core` never imports them |
| `backend/config/` also holds | `celery.py` (worker and beat composition root), `settings_test.py` |
| `backend/manage.py` | Entry point. Always run it as `uv run python manage.py ...` |

**A new domain is a new Django app** (`/new-django-app`, `DJANGO_STANDARDS` § 2). `core/` is not a
dumping ground — it is for what more than one app needs.

### Routes that exist today

All API paths derive from `API_PREFIX = "api"` (`config/settings.py`). Composed in `config/urls.py`;
project and plugin routes are added from `registry.api_routes`.

| Route | What | Defined in |
|-------|------|-----------|
| `/api/health/`, `/api/health/live/` | Liveness, public | `core/urls.py` |
| `/api/health/ready/` | Readiness (database reachable) | `core/urls.py` |
| `/api/health/components/` | Per-component health, permission-gated | `core/urls.py` |
| `/api/public/config/` | Public display identity (product name, tagline) | `core/urls.py` |
| `/api/me/navigation/`, `/api/me/bootstrap/` | Per-user nav and session bootstrap | `core/urls.py`, `users/urls.py` |
| `/api/auth/…` | login, refresh, logout, me, password forgot/reset/confirm, MFA setup/confirm/verify/disable, revoke-all sessions, invitation accept | `users/urls.py` |
| `/api/users/…` | Users module: list/create/retrieve/update, activate/deactivate, revoke sessions, invitations (list/create/revoke) | `users/urls.py` |
| `/api/rbac/…` | Permission catalog, roles (CRUD, set permissions), a user's role grants | `rbac/urls.py` |
| `/api/core/settings/…`, `/api/core/flags/…`, `/api/core/lookups/…` | Settings registry, feature flags, lookup values | `core/urls.py` |
| `/api/core/activity/`, `/api/core/activity/export/` | Audit log, GET only | `core/urls.py` |
| `/api/system/crypto/` | Encryption keyring status | `core/urls.py` |
| `/api/schema/`, `/api/docs/` | OpenAPI 3 (drf-spectacular), Swagger UI | `config/urls.py` |
| `/admin/` | Django admin — only when `ADMIN_ENABLED` | `config/urls.py` |

Anonymous routes (login, refresh, password forgot/reset, …) are registered by URL name in
`registry.public_routes` (`users/public_routes.py`); every other route is denied unless its view declares `required_permissions`.

### Models

| App | Models |
|-----|--------|
| `core` | `Setting`, `FeatureFlag`, `LookupValue`, `ActivityLog`, `JobSchedule`, `JobRun`, `JobState`, `Finding`, `OutboxMessage` |
| `users` | `User` ([ADR-0008](../adr/0008-custom-user-model-email-identity.md)), `UserSession`, `Invitation`, `MfaDevice`, `MfaRecoveryCode`, `PasswordResetToken`, `LoginAttempt` |
| `rbac` | `PermissionGroup`, `Permission`, `Role`, `RolePermission`, `UserRole` |

### Background work

`config/celery.py` builds the Celery app; tasks, queues and routes are generated from the job registry
(`core/jobs/`, [ADR-0012](../adr/0012-celery-from-day-one.md)). `docker-compose.yml` runs a `worker`; `beat`
is behind the `scheduler` profile (run exactly one). Outbox publishing and reconcilers live in
`core/outbox/` and `core/jobs/reconciler.py`.

### Settings

Everything environment-dependent comes from `.env` through `django-environ`, read in
`config/settings.py`. Nothing is hard-coded. The keys are listed in `backend/.env.example` —
**values never appear in docs, output or commits.**

### DRF defaults

`REST_FRAMEWORK` in `config/settings.py` sets:

| Setting | Value | Why it matters |
|---------|-------|----------------|
| `DEFAULT_AUTHENTICATION_CLASSES` | `users.authentication.CookieJWTAuthentication` | JWT in `httpOnly` cookies backed by `UserSession` rows ([ADR-0009](../adr/0009-jwt-in-httponly-cookies.md)) |
| `DEFAULT_PERMISSION_CLASSES` | `core.permissions.DefaultDeny` | **Fails closed.** A view that skips `core.api`'s `BaseAPIView`/`BaseViewSet` serves nobody (`dbx.E004`) |
| `EXCEPTION_HANDLER` | `core.api.exceptions.handler` | One error envelope: `{"error": {"code", "message", "details"?}}` |
| `DEFAULT_PARSER_CLASSES` | `JSONParser` only | No form or multipart parser by accident |
| `DEFAULT_PAGINATION_CLASS` | `PageNumberPagination`, `PAGE_SIZE: 20` | Every list is paginated by default |
| `DEFAULT_THROTTLE_CLASSES` / `_RATES` | Anon and user, plus `login`, `password_reset`, `mfa_verify`, `mfa`, `invitation_accept` scopes | Rate limiting is on |
| `NUM_PROXIES` | `TRUSTED_PROXY_COUNT` | Throttle keys ignore a spoofed `X-Forwarded-For` (DB-30) |
| `DEFAULT_SCHEMA_CLASS` | drf-spectacular `AutoSchema` | Every view appears in the OpenAPI doc |

---

## Frontend

### Layout

| Path | Holds |
|------|-------|
| `frontend/src/app/` | Routes. App Router — a folder with `page.tsx` is a route |
| `frontend/src/core/lib/api.ts` | The typed fetch wrapper. **The only module that makes HTTP calls** |
| `frontend/src/core/{shell,shells,components,theme,modules,messages}` | App shell, design system, the Users module, i18n messages |
| `frontend/src/proxy.ts` | Navigation guard (signed-out users never render private shells) |
| `frontend/tests/` | Vitest suite, including `tests/architecture/*` rule tests; run `npm test` |
| `frontend/public/` | Static assets served from `/` |

### The API boundary

`src/core/lib/api.ts` exists so that the base URL, error handling, headers and the one refresh-and-retry on a 401 are
written once. A component that calls `fetch()` directly bypasses all of it and will be wrong in a way
that only shows up in production. `AGENTS.md` § 3 makes this a hard rule.

`NEXT_PUBLIC_API_URL` is the base, defaulting to `http://localhost:8000`.

> ⚠️ `NEXT_PUBLIC_*` variables are **inlined into the client bundle** and are public. A secret must
> never take that prefix.

### Next 16 specifics

React 19 and Next 16.3.4. `params` and `searchParams` are **async** — advice written for Next 13/14
will not compile. The bundled agent docs at `frontend/node_modules/next/dist/docs/` are the source of
truth; read them rather than recalling.

---

## What does not exist yet

Stated plainly, because assuming otherwise wastes time. Source of truth: `BUILD_ORDER.md`.

| Not built | `BUILD_ORDER` |
|-----------|---------------|
| Safe outbound HTTP and the non-production guard | 7.4 |
| Retention engine | 7.5 |
| Webhooks, outbound and inbound | 7.6 |
| Notifications | 7.7 |
| Ops alerting | 7.8 |
| CSP enforcement and runtime branding (Report-Only nonce CSP exists in `src/proxy.ts`; static security headers 8.5b) | 8.5 |
| Platform completeness: full registry catalogue, API platform, data lifecycle, domain primitives, operations, engineering practice (no `CHANGELOG.md`) | Phase 9 |
| A second product built on the boilerplate | 10.1 |
| Sentry wiring: chosen ([ADR-0013](../adr/0013-sentry-only-error-tracking.md)), but no code initialises it or reads `SENTRY_DSN` | — |
| Production Docker: no release image or production Compose; `docker-compose.yml` is a development stack ([`../system-design/DEPLOYMENT.md`](../system-design/DEPLOYMENT.md) § 0) | — |

What is built and verified by CI (`.github/workflows/ci.yml`, the `AGENTS.md` § 2 gate): the backend
`pytest` suite on a PostgreSQL 16 service and the frontend lint, typecheck, vitest and `next build`.
Locally the suite defaults to in-memory SQLite (`config.settings_test`); SQLite-green is not the whole proof
([ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)).
