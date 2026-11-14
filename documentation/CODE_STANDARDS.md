# DjangoBaseX — code standards

> **Status:** Hub — checked 2026-11-14 · Rules and gold-standard files are built and enforced (architecture tests, ESLint bans); stack read from `backend/pyproject.toml` (Django `>=5.2,<6`, DRF, Celery 5.6, django-environ, Ruff, pytest) and `frontend/package.json` (Next.js 16.3.4, React 19.2.8, Tailwind `^4`, TanStack Query/Table, next-intl, zod, Vitest). Re-read the manifests before quoting a version.

This is the map. The deep rules live in [`DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) and [`NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md); the layer table is [`AGENTS.md`](../AGENTS.md) § 3. Recurring bugs: [`BUG_CLASSES.md`](system-design/BUG_CLASSES.md). Known defects: [`TECH_DEBT.md`](planning/TECH_DEBT.md). UI rules: [`UI_STANDARDS.md`](UI_STANDARDS.md). Related: [`PURPOSE.md`](PURPOSE.md), [`INVARIANTS.md`](INVARIANTS.md), [`TESTING.md`](TESTING.md), [`SECURITY.md`](SECURITY.md), [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md).

## A. Gold-standard files — copy these, don't invent a second way

The Users module is the reference ([`AGENTS.md`](../AGENTS.md) § 0). Paths relative to the repo root.

| Kind | Copy this | Notes |
|---|---|---|
| Model | `backend/users/models/user.py` (`User`); `backend/users/models/invitation.py` | fields, constraints, `Meta` only |
| Manager / queryset | `backend/users/models/user.py` (`UserQuerySet.visible_to`) on `backend/core/querysets.py` (`VisibleToQuerySet`) | fails closed: `.none()`, never `.all()` |
| Service | `backend/users/services/users.py` | `@transaction.atomic`, `on_commit` for side effects, typed errors with a `code` |
| Serializer | `backend/users/serializers.py` (`UserSerializer`, `UserCreateSerializer`) | shape + validate only |
| View / viewset | `backend/users/views.py` (`UserViewSet`) on `backend/core/api/viewsets.py` (`BaseViewSet`) | `required_permissions` map per action |
| URLs | `backend/users/urls.py` | mounted under `/api/` by `backend/config/urls.py` |
| Permission | `backend/core/permissions.py` (`DefaultDeny`, `HasPermission`) | codes like `users.users.view` |
| Error envelope | `backend/core/api/errors.py`, handler `backend/core/api/exceptions.py` | one shape for every error |
| Migration | `backend/users/migrations/0005_invitation.py` | generated, linear, reviewed |
| Admin | `backend/users/admin.py` | |
| Backend test | `backend/users/tests/test_users_api.py`; factories `backend/tests/factories.py` | state built through the real path |
| Architecture test | `backend/tests/architecture/test_settings_are_read.py` | a rule nothing reads is worse than none |
| Frontend API module | `frontend/src/core/lib/users.ts` over `frontend/src/core/lib/api.ts` | pages never shape requests |
| Frontend page | `frontend/src/app/(core)/users/page.tsx`, `frontend/src/app/(core)/users/[publicId]/page.tsx` | thin route, module does the work |
| Component | `frontend/src/core/components/Button.tsx`; `frontend/src/core/components/EmptyState.tsx` | |
| Hook (data) | `frontend/src/core/lib/query/use-api-query.ts` (`useApiQuery`, `useApiList`, `useApiMutation`) | no dedicated `hooks/` dir exists |
| Module (UI) | `frontend/src/core/modules/users/` | on the shells in `frontend/src/core/shells/` |
| Frontend test | `frontend/src/core/modules/users/users.test.tsx` (MSW + Testing Library) | |

## B. Rules

| Rule | Gold standard | Anti-pattern (taught by) | Check |
|---|---|---|---|
| **Layer boundaries.** Views parse/authorize/delegate; logic in `services/`; serializers shape only; querysets on the model ([`AGENTS.md`](../AGENTS.md) § 3, [`DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) § 3) | `UserViewSet.create` → `users_service.create_user` | business rule in a view or serializer; repeated `.filter()` chains in views | `uv run pytest` (incl. `tests/architecture/`); review against § 3 |
| **One way to do a thing.** Mirror the nearest existing example | Users module | a second HTTP client, second table, second form pattern | reviewer diff against the gold file |
| **Layer 2 scoping.** Every listable model has `visible_to(user)` that fails closed | `UserQuerySet.visible_to` | `.all()` as a default, "None means all" ([BC-01](system-design/BUG_CLASSES.md), [BC-02](system-design/BUG_CLASSES.md)) | a test as a user who holds nothing ([BC-45](system-design/BUG_CLASSES.md)) |
| **Every model with an owner or tenant field is registered for scoping.** `registry.scoping` entry (`ScopeSpec`): scoped with `visible_to`, or `not_scoped_because=<reason>`; a viewset scopes through `self.scope(...)` so writes use `writable_by` (404, not 403) | `backend/users/scoping.py`, `UserViewSet.get_queryset` | An owner/tenant column with no registration; `visible_to` called directly in a `BaseViewSet.get_queryset` (reads only) | `backend/tests/architecture/test_scoping.py` (fails on an empty scan) |
| **Settings via django-environ only.** No `os.environ` outside `config/settings.py`; add the key to `backend/.env.example` ([`DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) § 8) | `backend/config/settings.py` (`env = environ.Env(...)`) | hard-coded host/key/URL; env read in a module ([BC-15](system-design/BUG_CLASSES.md), [BC-37](system-design/BUG_CLASSES.md)) | `backend/tests/architecture/test_secret_env_reads.py`, `test_settings_are_read.py`, `backend/tests/test_env_example.py` |
| **No inline fetch.** Backend calls go through `src/core/lib/api` and `useApiQuery`/`useApiList`/`useApiMutation` ([`NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md) § 2) | `frontend/src/core/lib/users.ts` | `fetch()`/axios in a component; `useEffect` + `setLoading` (failed load shown as empty, [BC-42](system-design/BUG_CLASSES.md)) | `npm run lint` (RAW_FETCH, RAW_TANSTACK bans in `frontend/eslint.config.mjs`); `frontend/tests/architecture/no-effect-fetch.test.ts` |
| **Next.js 16: `params`/`searchParams` are async.** `await params`; read bundled docs, not memory ([`NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md) § 0) | `frontend/src/app/(core)/users/[publicId]/page.tsx` (`await params`) | synchronous `params.id` from older Next | `npm run typecheck`. Installed version: `frontend/node_modules/next/package.json` (absent until `npm ci`; manifest pins 16.3.4) |
| **Money through the core money type.** `Decimal`/`Money`, never float ([`DOMAIN_PRIMITIVES.md`](system-design/DOMAIN_PRIMITIVES.md)) | `backend/core/money.py` (`Money`, `to_money`, `allocate`) | float amounts; rounding in display ([BC-24](system-design/BUG_CLASSES.md), [BC-28](system-design/BUG_CLASSES.md)) | `backend/tests/architecture/test_no_float_money.py`; frontend shows via `<Money>` in `frontend/src/core/components/format/index.tsx` |
| **Transactions and side effects.** Writes in `@transaction.atomic`; email/queue only in `on_commit`; durable async via the outbox `enqueue()` | `create_user` in `users/services/users.py`; `backend/core/outbox/service.py` | send before commit ([BC-31](system-design/BUG_CLASSES.md)); check-then-act without a lock ([BC-30](system-design/BUG_CLASSES.md)) | `backend/tests/architecture/test_no_raw_dispatch.py`; concurrency tests on PostgreSQL ([`TECH_DEBT.md`](planning/TECH_DEBT.md) DB-29) |
| **Error shape.** Raise DRF/service exceptions; envelope `{"error": {"code", "message", "details"?}}`; never leak internals ([`DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) § 7) | `backend/core/api/errors.py` (`error_response`, `invalid_response`, `from_exception`) | hand-built `Response({"detail": ...})`; stack trace or SQL in a message | `uv run pytest` (API tests assert `error.code`); frontend decodes in `src/core/lib/api/errors.ts` |
| **Migrations.** Generated, linear, one per model change; never edit an applied one ([`DATABASE_MIGRATIONS.md`](system-design/DATABASE_MIGRATIONS.md)) | `users/migrations/0005_invitation.py` | model edit with no migration; branched history ([BC-39](system-design/BUG_CLASSES.md)) | `uv run python manage.py makemigrations --check --dry-run`; `backend/tests/architecture/test_migrations.py` |
| **Naming.** Python: Ruff defaults (`E,F,I,B,UP,DJ`, line 100); permission codes `app.resource.action`; TS: module files `Index.tsx`/`Show.tsx`/`Form.tsx`, hooks `useX`; match neighbours | `users.users.view` in `UserViewSet.required_permissions` | role names or code strings as literals ([BC-06](system-design/BUG_CLASSES.md)) | `uv run ruff check . && uv run ruff format --check .`; `test_permission_codes.py`, `test_no_role_name_literals.py` |
| **Comments explain why.** The constraint, the incident, the doc section — not what the line does | header of `frontend/src/core/shells/ResourceIndex.tsx` | `# increment i`; comments restating the code | reviewer; cite `§`/`BC-`/`DB-` ids as the sources do |
| **Frontend layering.** Core never imports project or plugin code; logic in `src/core/lib/`, not a page | `frontend/eslint.config.mjs` (`CORE_PATTERNS`) | importing `@/project` from core ([ADR-0010](adr/0010-platform-layer-is-logical.md)) | `npm run lint`; `backend/tests/architecture/test_core_boundary.py` |

Full gate (what CI runs): [`AGENTS.md`](../AGENTS.md) § 2.

## C. Performance rules

| Rule | Gold standard | Anti-pattern | Check |
|---|---|---|---|
| **No N+1.** `select_related` for FK, `Prefetch` for reverse/M2M, in `get_queryset` ([`DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) § 5) | `UserViewSet.get_queryset` (`prefetch_related(Prefetch("user_roles", ...), "mfa_devices")`); `InvitationViewSet` (`select_related("role", "invited_by")`) | serializer field that queries per row; known case: [`TECH_DEBT.md`](planning/TECH_DEBT.md) DB-52 | `assertNumQueries`/`django_assert_num_queries` in the list test; read the queryset against the serializer's fields |
| **Paginate every list.** DRF `PageNumberPagination`, `PAGE_SIZE` 20 (`backend/config/settings.py`); order deterministically (`order_by("email", "pk")`) | `UserViewSet` | unbounded `.all()` response; unstable ordering across pages | list test asserts `count`/`results` and page 2 |
| **Index what you filter/sort on.** `db_index=True` or `Meta.indexes` | `backend/users/models/invitation.py` (`email`, `expires_at`, `created_at`) | filter on an unindexed column in a big table | `EXPLAIN` on Postgres for new filters ([`DATA_MODEL.md`](system-design/DATA_MODEL.md)) |
| **Heavy or slow work in Celery, via the outbox.** Payloads are ids/scalars; never spawn work in a request | `backend/core/outbox/service.py` (`enqueue`); `backend/users/jobs.py` | sending mail/calling a third party inline in a view ([`TECH_DEBT.md`](planning/TECH_DEBT.md) DB-32) | `test_every_queue_has_a_worker.py`, `test_no_raw_dispatch.py` |
| **Frontend: server-paged tables, cached queries.** Lists use `useApiList` + `Pager`; mutations `invalidates: [...]` the root | `frontend/src/core/modules/users/Index.tsx` | loading every row client-side; manual refetch after write | `npm test`; check the Network tab shows one request per page change |

Not yet built (do not assume): mypy/type checking ([`TECH_DEBT.md`](planning/TECH_DEBT.md) DB-3).
