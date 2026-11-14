# DjangoBaseX — Domain (the platform's concepts)

> **Status:** Hub — checked 2026-11-14 · every concept in the glossary is built and read from code; notifications, soft delete and similar are in the 🔜 table. A boilerplate has no business domain: its "domain" is the vocabulary below. Products add their own nouns in `backend/project/` or a plugin.

Look a term up, go to its **owner** (the one module that decides it — change behaviour there, never in a consumer), then read the spec section. Spec files are in [`system-design/`](system-design/). The layout and recipes are in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Glossary

| Term | What it is | Owner in code | Read more |
|------|------------|---------------|-----------|
| **User** | The one account model; email is the identity | `backend/users/models/user.py` | [ADR-0008](adr/0008-custom-user-model-email-identity.md) |
| **Account state** | active · deactivated · superuser · two-factor on (users); pending · accepted · revoked · expired (invitations). Tone is decided once, the frontend renders it | `backend/users/statuses.py` | `FRONTEND_PLATFORM.md` § 13 |
| **Invitation** | A pending sign-up for an email, with a role; accepted, revoked or expired. Lifetime is env `INVITATION_LIFETIME` (seconds) today | `backend/users/models/invitation.py`, `backend/users/services/invitations.py` | `AUTH_BLUEPRINT.md` |
| **Session** | One `UserSession` row per issued refresh token — what makes the JWT revocable; the access token carries its id as `sid` | `backend/users/models/session.py`, `backend/users/tokens.py` | [ADR-0009](adr/0009-jwt-in-httponly-cookies.md), `AUTH_BLUEPRINT.md` § 6 |
| **Session marker** | Non-credential cookie the page guard reads; the access/refresh cookies are never sent on a navigation | `frontend/src/proxy.ts`, `frontend/src/core/lib/session/cookies.ts` | `FRONTEND_PLATFORM.md` § 8 |
| **Role** | A named bag of permissions, assigned to users (`UserRole`) | `backend/rbac/models.py`, `backend/rbac/services.py` | `RBAC_DESIGN.md` |
| **Permission** | A code `<module>.<feature>.<action>` declared in code, seeded to the DB; checked by the declarative gate every endpoint inherits | `backend/core/permissions.py`, catalog per app (`backend/users/permissions.py`) | `AUTH_BLUEPRINT.md` § 7 |
| **Registry** | The seam: modules declare things (permissions, nav, routes, settings, jobs, …) at boot; core never names a module | `backend/core/registry.py` (`registry`) | `EXTENSIBILITY.md` §§ 3, 7 |
| **Plugin** | An external package (`djx_<name>`) discovered from a `plugin.toml` manifest; every prefix derives from its label | `backend/core/plugins.py`, `scripts/plugins.py`, example `examples/plugins/notes/` | `EXTENSIBILITY.md` § 12 |
| **core vs `project/`** | `core`, `users`, `rbac` are the platform; `backend/project/` (and `frontend/src/project/`) is where one product plugs in. Dependencies point inward | `backend/tests/architecture/test_core_boundary.py` | [ADR-0010](adr/0010-platform-layer-is-logical.md) |
| **Setting** | A typed, admin-editable runtime value declared in code (`Bool`, `Int`, `Choice`, …) and stored in `Setting`; no row means the declared default | `backend/core/settings_registry.py`, `backend/core/settings_service.py` | `CONFIGURATION.md` § 9 |
| **Feature flag** | A registered on/off switch, evaluated per user/role, with an expiry | `backend/core/flags.py` | `CONFIGURATION.md` § 11 |
| **Guard mode** | A flag-like `off` · `log_only` · `enforce` switch, always paired with its `<key>.mode` setting | `backend/core/guards.py` | `CONFIGURATION.md` § 13 |
| **Lookup / vocabulary** | An admin-editable value set (`LookupValue`) seeded after migrate; models point at it with `LookupField` | `backend/core/lookups.py` | `CONFIGURATION.md` § 14 |
| **Environment identity** | `APP_ENV`, fail-closed: only an allow-list is non-production; `is_production_like()` is the only environment test | `backend/core/env.py` | `CONFIGURATION.md` § 4 |
| **Project identity** | One product name derives slug, cookie prefix and tagline | `backend/core/identity.py` | `CONFIGURATION.md` § 7 |
| **Audit event** | An append-only `ActivityLog` row: actor, target, action key (`module.entity.verb`), scrubbed changes | `backend/core/audit.py`, actions in `backend/core/audit_actions.py` | `DATA_LIFECYCLE.md` § 4 |
| **Job** | A `JobSpec` (name, queue, schedule, flags) pointing at `def run(ctx: JobContext) -> int` | `backend/core/registry.py` (spec), `backend/core/jobs/` | `JOBS_AND_INTEGRATIONS.md` § 1 |
| **Retention policy** | A registered `RetentionPolicy` (model, timestamp, optional filter and row cap, data class, floor, opt-in); one engine deletes by it, in batches, for the daily job and `manage.py retention`. Its window is the setting `retention.<key>.days` (empty keeps forever; below the floor is refused); the audit log is opt-in | `backend/core/retention/` (engine), `backend/core/registry.py` (spec), `backend/users/retention.py` | `DATA_LIFECYCLE.md` § 6 |
| **Job run** | One `JobRun` row per execution, written from Celery signals, never by the job | `backend/core/jobs/recorder.py` | `JOBS_AND_INTEGRATIONS.md` § 7 |
| **Event** | A registered domain event `<module>.<entity>.<verb>` (`EventDef`); `external=True` puts it in the webhook catalogue, and every catalogue event needs an `emit()` call site | `backend/core/registry.py` (`EventRegistry`), `backend/users/events.py` | `JOBS_AND_INTEGRATIONS.md` § 16 |
| **Webhook endpoint** | A platform-owned URL subscribed to catalogue events; encrypted signing secret shown once, rotation with overlap, `is_active` (human) and `disabled_at` (breaker) kept apart | `backend/core/models.py` (`WebhookEndpoint`), `backend/core/webhooks/service.py` | `JOBS_AND_INTEGRATIONS.md` § 16 |
| **Notification purpose** | One kind of message a module sends (`users.password_reset`), declared in code with its audience, default channels, `mandatory` (cannot be switched off) and `carries_token` flags; callers name it and never a destination | `backend/core/registry.py` (`NotificationPurpose`), `backend/users/notifications.py` | `NOTIFICATIONS_AND_ALERTING.md` § 1 |
| **Notification route** | Admin-editable data saying where a broadcast purpose goes on a channel (email addresses); every change is audited | `backend/core/models.py` (`NotificationRoute`), `backend/core/notifications/service.py` | `NOTIFICATIONS_AND_ALERTING.md` § 1 |
| **Notification channel** | A transport adapter (`email`, `in_app`) that renders and sends one message and never raises into its caller | `backend/core/notifications/channels.py` | `NOTIFICATIONS_AND_ALERTING.md` § 2 |
| **In-app notification** | A row in the bell: read state is per user, resolved state is shared, one open row per recipient x purpose x object | `backend/core/models.py` (`Notification`), `backend/core/notifications/inapp.py` | `NOTIFICATIONS_AND_ALERTING.md` § 8 |
| **Notification preference** | A user's (or the system default's) on/off per purpose x channel; resolves user row, system row, code default; mandatory purposes cannot be opted out | `backend/core/models.py` (`NotificationPreference`), `backend/core/notifications/engine.py` | `NOTIFICATIONS_AND_ALERTING.md` § 5 |
| **Delivery** | One event x endpoint, ids-only payload, signed `v1=` HMAC over `timestamp.body`; the log row with Redeliver and the outbox row that carries it | `backend/core/webhooks/delivery.py`, `WebhookDelivery` | `JOBS_AND_INTEGRATIONS.md` § 16 |
| **Inbound webhook** | A third-party callback: verified over the raw body first, then deduplicated by a unique key in the database, stored minimised, processed later | `backend/core/webhooks/inbound.py`, `InboundWebhookEvent` | `JOBS_AND_INTEGRATIONS.md` § 17 |
| **Outbox row** | An `OutboxMessage` written in the caller's transaction, then leased, sent and settled; the only way to send a side effect | `backend/core/outbox/service.py` | `JOBS_AND_INTEGRATIONS.md` § 12 |
| **Reconciler** | A `Reconciler` that re-examines rows stuck in a pending state (e.g. expired leases) and fixes or raises a finding | `backend/core/jobs/reconciler.py`, `backend/core/outbox/recovery.py` | `JOBS_AND_INTEGRATIONS.md` § 11 |
| **Lock** | Redis single-flight lease (memory store in tests); Postgres transaction advisory lock for DB work | `backend/core/locks.py` | `JOBS_AND_INTEGRATIONS.md` § 9 |
| **Finding** | A `Finding` row: a problem raised, touched, cleared or resolved by kind and subject | `backend/core/findings.py` | `DOMAIN_PRIMITIVES.md` § 8 |
| **Health rungs** | `live` (no I/O) · `ready` (database + cache) · `components` (every probe; only a critical one can be `down`) | `backend/core/observability/health.py` | `OBSERVABILITY.md` § 6 |
| **Doctor** | A registered check run by `manage.py doctor`; findings are failure or advisory, known backlog is never "healthy" | `backend/core/doctors.py`, `backend/core/management/commands/doctor.py` | `OBSERVABILITY.md` § 12 |
| **Data-plane check** | A boot-time/doctor check that required rows exist (an active superuser, the administrator role) | `backend/core/dataplane.py` | `OBSERVABILITY.md` § 7 |
| **Money type** | `Money`/`Rate` on `Decimal` with ISO-4217 minor units; floats refused | `backend/core/money.py` | `DOMAIN_PRIMITIVES.md` § 1 |
| **Request id / scrubber** | Every request gets an id carried into logs; one scrubber redacts secrets everywhere | `backend/core/observability/request_id.py`, `backend/core/observability/scrub.py` | `OBSERVABILITY.md` §§ 1, 3 |
| **Encryption** | Fernet keyed per purpose, multi-key rotation; encrypted columns are registered | `backend/core/crypto.py`, `registry.encrypted_fields` | `JOBS_AND_INTEGRATIONS.md` § 25 |
| **Navigation manifest** | Server-built menu that is also the frontend route gate | `backend/core/navigation.py`, `frontend/src/core/shell/nav/` | `FRONTEND_PLATFORM.md` § 10 |
| **Outbound HTTP purpose** | A registered `HttpPurpose` (timeouts, hosts, size cap, retry); `core.http.client(purpose)` is the only way to call another system, and every address is vetted inside the connect (no private ranges, no DNS rebinding) | `backend/core/http/` | `JOBS_AND_INTEGRATIONS.md` § 20 |
| **Non-production guard** | On unless `APP_ENV` is exactly `production`: HTTP outside `OUTBOUND_ALLOWLIST` gets a synthetic 423; mail goes only to `NONPROD_TEST_RECIPIENT` | `backend/core/http/guard.py`, `backend/core/mail/backends.py`, `core.env.outbound_guard_active` | `JOBS_AND_INTEGRATIONS.md` § 27 |
| **Provider error** | One hierarchy for upstream failures; `raise_for_upstream()` is the only status mapping; an upstream 401/403 is our 502 | `backend/core/providers/errors.py` | `JOBS_AND_INTEGRATIONS.md` § 20 |
| **Invariant** | A DB constraint mapped to a typed error so the API answers cleanly | `backend/core/invariants.py` | `DATA_LIFECYCLE.md` § 10 |

## Core flows

**Login → session → bootstrap → nav**

| Step | File |
|------|------|
| Login page calls the API through the single client | `frontend/src/app/(core)/login`, `frontend/src/core/lib/auth.ts`, `frontend/src/core/lib/api/client.ts` |
| View delegates to the service; lockout and MFA step live in services | `backend/users/views.py` (`LoginView`), `backend/users/services/auth.py`, `backend/users/services/lockout.py`, `backend/users/services/mfa.py` |
| Session row created, JWTs minted, cookies set | `backend/users/tokens.py`, `backend/users/cookies.py` |
| Each request: authenticate, confirm the session row is live, check CSRF | `backend/users/authentication.py` |
| Page guard on the marker cookie | `frontend/src/proxy.ts` |
| Bootstrap payload assembled from contributors | `backend/core/bootstrap.py`, `backend/users/bootstrap.py`, `frontend/src/core/lib/bootstrap.ts` |
| Effective permissions feed `can()`; menu comes from `/api/me/navigation/` | `frontend/src/core/lib/permissions.tsx`, `backend/core/navigation.py`, `frontend/src/core/shell/nav/use-nav.ts` |

**Job: register → beat → run → job-run row**

| Step | File |
|------|------|
| Declare a `JobSpec`, register in `ready()` | `backend/users/jobs.py`, `backend/users/apps.py` |
| Task generated per spec | `backend/core/jobs/celery.py` |
| Schedules synced to beat rows (post-migrate, or `manage.py sync_schedules`) | `backend/core/jobs/schedules.py` |
| Worker executes, resolves the function | `backend/core/jobs/runner.py` |
| Signals write the `JobRun` row; health reads it | `backend/core/jobs/recorder.py`, `backend/core/jobs/health.py` |

**Outbox: write in transaction → lease → send → state**

| Step | File |
|------|------|
| `enqueue()` inside the caller's transaction; kick after commit | `backend/core/outbox/service.py` |
| `drain_job` claims due rows (`SKIP LOCKED`) with a lease token | `backend/core/outbox/service.py` (`claim`), `backend/core/outbox/jobs.py` |
| Topic handler sends and returns an `Outcome` | `backend/core/outbox/outcome.py` |
| `settle()` sets the row state; unknown results open a finding | `backend/core/outbox/service.py` (`settle`, `resolve_unknown`) |
| Expired leases recovered | `backend/core/outbox/recovery.py` |

## 🔜 Planned (not built — do not assume)

| Concept | BUILD_ORDER item |
|---------|------------------|
| Ops alerting | 7.8 |
| Static security headers, revalidation, logos, host-matched identity | 8.5b |
| Full registry catalogue, plugin lifecycle | 9.1 |
| API platform | 9.2 |
| Data lifecycle (soft delete, recycle bin) | 9.3 |
| Domain primitives beyond money (number sequences, state machines) | 9.4 |
| Error tracking via Sentry ([ADR-0013](adr/0013-sentry-only-error-tracking.md); no code reads `SENTRY_DSN` yet) | not in a numbered item |

Items are in [`planning/BUILD_ORDER.md`](planning/BUILD_ORDER.md).
