# DjangoBaseX — testing

> **Status:** Hub — checked 2026-11-14 · built: pytest + pytest-django + factory_boy harness, 32 backend architecture tests, Vitest with 14 frontend architecture tests, CI on PostgreSQL 16; not built: coverage floors, browser checks.

Replaces `planning/TESTING_STRATEGY.md`. Deep spec: [`ENGINEERING_PRACTICES.md`](system-design/ENGINEERING_PRACTICES.md) Part A (tests) and Part B (CI). Purpose and tie-breakers: [`PURPOSE.md`](PURPOSE.md). Sibling docs: [`INVARIANTS.md`](INVARIANTS.md), [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md), [`system-design/TRAPS.md`](system-design/TRAPS.md).

**Inventory (observed with `find`, 2026-11-14):** 92 backend `test_*.py` files under `backend/` (37 in `tests/` top level, 32 in `tests/architecture/`, the rest in `tests/core`, `tests/harness`, `tests/infra`, `tests/observability`, `users/tests`); 36 frontend `*.test.ts(x)` files (14 in `frontend/tests/architecture/`, `frontend/tests/lint-smoke.test.ts`, the rest next to their module in `frontend/src/`).

## 1. The gate

Exactly [`AGENTS.md`](../AGENTS.md) § 2; CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs the same, each step blocking (no `continue-on-error`).

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
cd backend && uv run python manage.py check
cd backend && uv run python manage.py makemigrations --check --dry-run   # after ANY model change
cd backend && uv run pytest
cd backend && uv run ruff check --config pyproject.toml ../scripts ../examples   # + format --check
cd frontend && npm run lint && npm run typecheck && npm test
python3 .claude/hooks/test_agent_guard.py          # only when .claude/hooks/ changed
```

CI differences (derived from `ci.yml`): backend runs on **PostgreSQL 16 + Redis 7.4** (`TEST_DATABASE_URL`), local runs on in-memory SQLite; frontend CI adds `npm run build` (not in the local gate: slow, writes `.next/`); both jobs run **twice**, bare and with `examples/plugins/notes` installed. Procedure: `/verify` ([`.claude/skills/verify/SKILL.md`](../.claude/skills/verify/SKILL.md)). **Run each command separately** so one failure does not hide the next; trust exit codes, not printed text.

## 2. What must be tested, per change

| Change | Must have | Why |
|---|---|---|
| New/changed endpoint | A permission-denied test (403 for a session lacking the code) **and** the allowed path; the route is covered automatically by `test_route_enforcement.py` | Gold: `backend/users/tests/test_users_api.py` |
| New permission code | Declared in the catalog and referenced; `test_permission_codes.py` checks both directions | A referenced-but-undeclared code denies everyone |
| Model change | A migration; `makemigrations --check --dry-run` green; `test_migrations.py` | Branched chain is silent until deploy |
| Bug fix | A **failing test first**, then the fix; name it by the ticket/bug class ([`BUG_CLASSES.md`](system-design/BUG_CLASSES.md)) | Proves the test can fail |
| Plugin | `test_plugin_conventions.py` passes with it installed (CI does this with `notes`) | Boundaries, label, table names |
| New background job / queue / beat entry / pending state | The matching architecture test passes (§ 3) | Silent never-runs |
| Setting, flag, encrypted column | Registered; `test_settings_are_read`, `test_no_expired_flags`, `test_encrypted_columns_are_registered` | A setting nothing reads is a defect |
| Frontend data / route / message | Through `src/core/lib/api`; `tests/architecture/*` guards (§ 3) pass; a unit test beside the module | Gold: `frontend/src/core/modules/users/users.test.tsx` |
| Anything touching scrub/crypto/auth | Dedicated test (`test_scrub*.py`, `test_crypto.py`, `users/tests/test_auth_flow.py`) | See [`SECURITY.md`](SECURITY.md) |

## 3. Architecture tests — what each guarantees

Pattern: AST/source scans with **two-way ratchets** (`backend/tests/architecture/_ratchet.py`): new offenders fail, and a fixed offender must be deleted from its allow-list, so lists only shrink ([`ENGINEERING_PRACTICES.md`](system-design/ENGINEERING_PRACTICES.md) § 2). Shared helpers: `sources.py`, `url_walk.py`, `plugin_rules.py`, `permission_refs.py`.

| Test (`backend/tests/architecture/`) | Guarantees |
|---|---|
| `test_route_enforcement.py` | Every `/api/` route, every method, anonymous → 401/403; **404 also fails** (handler looked up before checking who asked). Exemptions only via `core.routes.public_routes()` |
| `test_public_routes.py` | The public-route ledger is pinned; opening a route means editing the expected set in the same reviewed change |
| `test_permission_codes.py` (+ `test_permission_refs_scanner.py`) | Every referenced code is in the catalog and vice-versa; the scanner itself is pinned on synthetic source |
| `test_core_boundary.py` | Platform apps import only each other, Django, third parties — never `project/` or a plugin (ADR-0010) |
| `test_platform_without_project.py` | Copy of backend without `project/` boots and routes resolve |
| `test_plugin_conventions.py` | Each installed plugin: no cross-plugin/`project` imports, explicit `app_label`, table prefixes |
| `test_migrations.py` | Linear chain, no missing migrations |
| `test_secret_env_reads.py` | Credential-shaped env keys read only in `config/settings*.py` |
| `test_encrypted_columns_are_registered.py`, `test_no_decrypt_on_access.py` | `*_ciphertext` columns registered; no decrypt on attribute access |
| `test_audit_rules.py` | Only `core.audit.record()` writes the activity log; action literals are registered |
| `test_no_raw_dispatch.py`, `test_no_blanket_autoretry.py`, `test_every_queue_has_a_worker.py`, `test_beat_entries_are_registered.py`, `test_every_pending_state_has_a_reconciler.py`, `test_no_session_advisory_locks.py` | Jobs: one enqueue path, classified retries, no orphan queue/beat entry/pending state, no session advisory locks |
| `test_no_float_money.py`, `test_no_locale_literals.py`, `test_no_role_name_literals.py` | No float money, no hard-coded currency/timezone, roles classified by column |
| `test_settings_are_read.py`, `test_no_expired_flags.py`, `test_no_boilerplate_identity.py` | Settings are consumed; expired flags fail; core never spells the boilerplate's name |

Frontend (`frontend/tests/architecture/`): `no-effect-fetch`, `hand-typed-contracts`, `contracts`, `query-keys`, `route-manifest`, `module-contract`, `table-engine-boundary`, `messages`, `plugin-messages`, `untranslated-pages`, `no-false-empty`, `no-raw-colour-on-tokens`, `sortable-has-key`, `confirm-host`. Config: [`frontend/vitest.config.ts`](../frontend/vitest.config.ts) (jsdom, `TZ=UTC`, forked isolated processes, non-watch `vitest run`).

## 4. Fixtures that build state through the real path

Config: `backend/pyproject.toml` (`DJANGO_SETTINGS_MODULE = config.settings_test`, `--strict-markers -ra`); `backend/config/settings_test.py` pins every env value so a developer's `.env` cannot change a result.

| Fixture / helper | Where | Gold use |
|---|---|---|
| Test-database guard (refuses a non-test DB, never prints the password) | `backend/tests/harness/db_guard.py`, wired in `backend/conftest.py` | `tests/harness/test_harness_db_guard.py` |
| `_hermetic_cache` (autouse) | `backend/conftest.py` | no throttle/lockout leaks between tests |
| `setting_override(key, value)` — real `set_value` writer, audited, rolled back | `backend/conftest.py` | `tests/test_settings_service.py` |
| `audit_rows(action=None)` — activity-log rows since requested | `backend/conftest.py` | `tests/test_config_audit.py` |
| `UserFactory` (`DEFAULT_PASSWORD`) | `backend/tests/factories.py` | `users/tests/test_users_api.py` |
| `session(*codes, superuser=)` — a user with a role built via `rbac.services`, logged in through `/api/auth/login/` | defined in `users/tests/test_users_api.py` | copy it; never force-login or bypass permissions |

Rule: build state with services and the real login, not by writing rows, and not as a superuser unless the test is about superusers (a check run as admin proves nothing about real users).

## 5. What SQLite in-memory does NOT prove

Local `pytest` uses `sqlite://:memory:`; CI uses PostgreSQL 16 ([ADR-0005](adr/0005-sqlite-for-dev-postgres-by-url.md)). SQLite proves logic, not locking, `SELECT … FOR UPDATE SKIP LOCKED` (a no-op on SQLite), advisory locks, constraint/isolation behaviour, or a second connection. Such tests carry `skipif(connection.vendor != "postgresql", reason=…)` so the skip prints its reason (`-ra`):

- `tests/core/outbox/test_outbox.py::test_two_drainers_never_claim_the_same_row` — 4 concurrent drainers, 200 rows
- `tests/core/jobs/test_recorder.py::test_a_rolled_back_job_still_records_its_failure` — needs the recorder on its own connection (`tests/core/jobs/dbs.py`)
- `tests/core/test_locks.py` — advisory locks

For anything touching these, point at Postgres: `TEST_DATABASE_URL=postgres://… uv run pytest` (the guard still checks the host). A green SQLite run with those tests skipped is **not** done; say so in the report.

## 6. Run one test

```bash
cd backend && uv run pytest tests/architecture/test_route_enforcement.py -q
cd backend && uv run pytest users/tests/test_users_api.py::test_you_cannot_deactivate_yourself -q
cd frontend && npx vitest run src/core/lib/api/errors.test.ts
```

## 7. Report format

Per command: command · pass/fail · count. List **new failures** separately from **pre-existing** (compare with a clean `HEAD` baseline run), every skipped test with its reason, and what was not run (e.g. Postgres-only tests, `npm run build`). Label claims observed / derived / inferred / unknown. Never summarise green over a red run (`AGENTS.md` § 1 rule 9).

## 8. Not built (do not assume)

- **Coverage floors.** `pytest-cov` is installed but neither `pyproject.toml` nor `ci.yml` sets a floor; design in [`ENGINEERING_PRACTICES.md`](system-design/ENGINEERING_PRACTICES.md) § 10. Rule when added: set to measured reality, raise deliberately, never aspirational.
- **Browser checks** from the nav registry (§ 11 of the same doc) — no runner in the repo.
