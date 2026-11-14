# DjangoBaseX — invariants

> **Status:** Accepted — checked 2026-11-14 · every line is true in the code today

The hard rules a change must never break. One line each, written as an instruction. Every line names its
**source** (an Accepted ADR in [`ADR.md`](ADR.md) or the contract in [`../AGENTS.md`](../AGENTS.md)) and,
where one exists, the **test that goes red** when it is broken. The source holds the reasoning.

- **A change that would break one: stop and ask, quoting its number.** Changing one needs a superseding ADR,
  never a quiet edit.
- **Add a line only when an ADR is accepted or the contract changes.** Never invent one, and never list a
  rule for code that does not exist yet (that belongs in [`planning/BUILD_ORDER.md`](planning/BUILD_ORDER.md)).
- Paths below are relative to `backend/tests/` unless they start with `frontend/`.

## What this repository is

1. **Keep it a boilerplate:** no product identity, client name or single-product domain model in the core
   ([PURPOSE](PURPOSE.md) § What DjangoBaseX is not; AGENTS § 3) — `architecture/test_no_boilerplate_identity.py`.
2. **Never name another codebase, company or client** anywhere in the repo — docs, code, comments, commits,
   memory (AGENTS § 1 rule 5a). Record the mechanism and the reason, never the source.
3. **Treat the repo as public:** no real credentials, customer data or internal URLs; demo credentials stay
   obviously fake (AGENTS § 1 rule 5).

## Platform shape

4. **The platform never imports the product.** `core`, `users` and `rbac` import only each other, Django and
   third-party packages; product code lives in `backend/project/` or a plugin
   ([ADR-0010](adr/0010-platform-layer-is-logical.md)) — `architecture/test_core_boundary.py`.
5. **Deleting `project/` must leave a working platform** ([ADR-0010](adr/0010-platform-layer-is-logical.md))
   — `architecture/test_platform_without_project.py`.
6. **Plugins register through the registries and keep the plugin conventions**
   ([ADR-0010](adr/0010-platform-layer-is-logical.md), [ADR-0015](adr/0015-plugin-docs-live-in-the-plugin.md))
   — `architecture/test_plugin_conventions.py`.
7. **The backend is an API only (DRF);** the only server-rendered HTML is `/admin/` and the API docs
   ([ADR-0002](adr/0002-api-first-drf-not-django-templates.md)).
8. **No organisation model in the core;** every model a non-superuser can list exposes
   `objects.visible_to(user)`, which fails closed ([ADR-0011](adr/0011-no-organisation-in-core.md)).
9. **Keep layers thin:** views do HTTP only, logic lives in `services.py`, serializers have no queries or
   side effects (AGENTS § 3).

## Access and security

10. **Every `/api/` route refuses an anonymous caller** unless it is in the public-route ledger
    ([ADR-0009](adr/0009-jwt-in-httponly-cookies.md)) — `architecture/test_route_enforcement.py`,
    `architecture/test_public_routes.py`.
11. **Every permission code referenced in code exists in the catalog, and every catalog code is used**
    (AGENTS § 3; RBAC) — `architecture/test_permission_codes.py`.
12. **Never compare a role by its name in code;** roles are classified by column — `architecture/test_no_role_name_literals.py`.
13. **Browser auth is JWT in `httpOnly` cookies backed by a database session row;** never a token in
    `localStorage` ([ADR-0009](adr/0009-jwt-in-httponly-cookies.md)).
14. **The user is `users.User`, identified by email,** with boolean account states
    ([ADR-0008](adr/0008-custom-user-model-email-identity.md)).
15. **Read secrets from the environment in settings only,** via `django-environ`; never print a `.env` value
    (AGENTS § 1 rule 6, § 3) — `architecture/test_secret_env_reads.py`.
16. **Never decrypt on attribute access, and register every `*_ciphertext` column**
    — `architecture/test_no_decrypt_on_access.py`, `architecture/test_encrypted_columns_are_registered.py`.
17. **Only `core.audit.record()` writes the activity log** — `architecture/test_audit_rules.py`.

## Data and money

18. **Every model change ships its migration, and the migration chain stays linear** (AGENTS § 2) —
    `makemigrations --check --dry-run`, `architecture/test_migrations.py`.
19. **No float ever holds money;** use the core money type — `architecture/test_no_float_money.py`, `test_money.py`.
20. **A business rule the database can hold is held by the database,** and its refusal maps to one typed
    error — `test_invariants.py`.
21. **Nothing hard-coded:** no currency code, timezone, host, brand or role name in code; values come from
    env, the settings registry or a lookup ([PURPOSE](PURPOSE.md) principle 7) —
    `architecture/test_no_locale_literals.py`, `architecture/test_no_boilerplate_identity.py`.
22. **A setting nothing reads is a defect, and an expired flag fails CI** — `architecture/test_settings_are_read.py`,
    `architecture/test_no_expired_flags.py`.
23. **SQLite in development, PostgreSQL by `DATABASE_URL`, no code change**
    ([ADR-0005](adr/0005-sqlite-for-dev-postgres-by-url.md)).

## Jobs and integrations

24. **Run background work as registered Celery jobs** ([ADR-0012](adr/0012-celery-from-day-one.md)); dispatch
    only through `core.jobs.enqueue()` — `architecture/test_no_raw_dispatch.py`.
25. **Every beat entry names a registered task, and every queue has a worker** —
    `architecture/test_beat_entries_are_registered.py`, `architecture/test_every_queue_has_a_worker.py`.
26. **Never retry blanket `Exception`;** classify with `RetryPolicy` — `architecture/test_no_blanket_autoretry.py`.
27. **Every transient ("pending") state has a reconciler** — `architecture/test_every_pending_state_has_a_reconciler.py`.
28. **No session-level advisory locks** — `architecture/test_no_session_advisory_locks.py`.
29. **Never build an error tracker in the core** (no errors table, grouping or screen); error tracking is
    Sentry ([ADR-0013](adr/0013-sentry-only-error-tracking.md)). The Sentry wiring itself is not built yet
    — no code reads `SENTRY_DSN` today.

## Frontend

30. **All frontend data goes through `src/core/lib/api.ts`;** never a raw `fetch` in a component (AGENTS § 3)
    — ESLint `no-restricted-globals` in `frontend/eslint.config.mjs`, `frontend/tests/architecture/no-effect-fetch.test.ts`.
31. **Never hand-write an API type the OpenAPI contract can generate;** each fixed view retires its entry —
    `frontend/tests/architecture/hand-typed-contracts.test.ts`.
32. **Write Next.js 16 / React 19 code from the installed version's docs, not memory** — `params` and
    `searchParams` are async (AGENTS § 1).

## Tooling, docs and git

33. **One agent contract — the root `AGENTS.md`;** `CLAUDE.md`/`GEMINI.md` only import it and `.claude/` only
    enforces and points ([ADR-0006](adr/0006-one-agent-contract.md), [ADR-0007](adr/0007-claude-code-harness.md)).
34. **`uv` manages Python; Ruff is the only lint/format tool** ([ADR-0003](adr/0003-uv-manages-the-backend-toolchain.md),
    [ADR-0004](adr/0004-ruff-is-the-only-python-tool.md)).
35. **Never commit or push without the owner's explicit yes; never add AI attribution;** branch is `main`
    (AGENTS § 1, § 4) — refused by `.claude/hooks/agent_guard.py`.
36. **Update `DAILY_CHANGES.md` in the same change as the code** (AGENTS § 1 rule 8).
37. **Core releases follow SemVer** ([ADR-0014](adr/0014-semver-for-core-releases.md)).
