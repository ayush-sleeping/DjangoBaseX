# Daily Changes

**The running log. One entry per task, written in the same change as the code** — not afterwards
(`AGENTS.md` § 1, rule 8).

**Why in the same change:** a log written later is a log written from memory, and the part that gets
forgotten is always the same part — *why*, and *what was tried and rejected*. That is the only part
worth reading six months on.

Newest first.

### Format

```markdown
## YYYY-MM-DD

### <Short title>
**What:** what changed, in one or two lines.
**Why:** the reason. If it fixes something, what was broken and how it showed up.
**Files:** the paths that changed.
**Verification:** the commands run, and their real result — including failures.
**Notes:** anything the next person would otherwise have to rediscover. Optional.
```

---

## 2026-10-11

### BUILD_ORDER 2.2: architecture tests — route enforcement and migrations
**What:**
- New `core/routes.py` `PUBLIC_ROUTES`, the exemption ledger: `core:health`, `schema` and
  `swagger-ui`, each with a reason (`AUTH_BLUEPRINT.md` § 9.2).
- New `tests/architecture/`:
  - `url_walk.py` renders every route to a callable path, and raises on any converter or regex it
    cannot render rather than skipping it;
  - `test_route_enforcement.py` calls every non-exempt `/api/` route anonymously with
    GET/POST/PUT/PATCH/DELETE and fails on anything but 401/403, with a specific hint on 404. It also
    guards against an empty walk, and a meta-test runs the checker on `fake_urls.py` (gated, open
    and lookup-first views);
  - `test_public_routes.py` pins the ledger, and checks every key resolves and has a reason;
  - `test_migrations.py` checks one head per app, `makemigrations --check` inside pytest, and a
    table for every managed model.
- `API_DESIGN.md` § Authentication now states the rule.

**Why:** `BUILD_ORDER` 2.2. These tests reject a whole class of mistake rather than one instance:
an endpoint shipped open, or a migration chain that only breaks at deploy. They must exist before
1.1 adds the first gated endpoints.
**Files:**
- New: `backend/core/routes.py`,
  `backend/tests/architecture/{__init__,url_walk,fake_urls,test_route_enforcement,test_public_routes,test_migrations}.py`.
- Changed: `documentation/DAILY_CHANGES.md`, `documentation/planning/{BUILD_ORDER,TESTING_STRATEGY}.md`,
  `documentation/system-design/API_DESIGN.md`.

**Verification:**
- `uv run pytest`: 43 passed. The first run had 1 failure: `test_no_model_change_is_missing_a_migration`
  hit "Database access not allowed", because `makemigrations` checks the applied history. Marked
  `django_db`; re-run green.
- **Acceptance, break 1:** with `core:health` removed from `PUBLIC_ROUTES`, the route test failed
  with `GET /api/health/ [core:health] -> 200` (and 405 for the other four methods) plus the fix
  hint. Restored, it passed.
- **Acceptance, break 2:** two throwaway `users/0002_probe_branch_{a,b}.py` migrations failed the
  head test with `users: 0002_probe_branch_a, 0002_probe_branch_b. Merge with makemigrations
  --merge…`. Both files were deleted and `users/migrations` is clean.
- `ruff check`: passed. `ruff format --check`: the first run flagged `test_migrations.py`; after
  `ruff format`, 38 files formatted.

**Notes / still open:**
- No gated `/api/` route exists yet, so the real-route test checks zero routes today. That is why
  the meta-test and the "walk found the API" guard exist. 1.1's endpoints are the first it enforces.
- `schema` and `swagger-ui` are public today. Gating them to `DEBUG` or `SCHEMA_PUBLIC` is noted in
  the ledger's reason and is not done.
- `/admin/` sits outside `/api/`, so this test does not see it. That is DB-15's point, and
  `ADMIN_ENABLED` is the control.
- Not here: the `dbx.E001`/`E007` boot checks (1.2a), the boundary test (needs the `project/` split,
  1.6), and plugin conventions (3.2).

### BUILD_ORDER 2.1: pytest, with a guarded and hermetic harness
**What:**
- `pytest`, `pytest-django`, `factory-boy` and `pytest-cov` added to the `dev` group.
  `[tool.pytest.ini_options]` selects `config.settings_test`, `--strict-markers -ra`.
- **`config/settings_test.py`** pins every env value the base settings read *before* importing them,
  so a developer's `.env` cannot leak in. The database is in-memory SQLite unless `TEST_DATABASE_URL`
  is set; cache, email and storage are in memory; MD5 is the hasher.
- **Root `backend/conftest.py`:** the test-database guard (`tests/harness/db_guard.py`,
  `OPERATIONS.md` § 11) runs in `pytest_configure`, before any database is created, and refuses an
  empty name, a non-`test_` name, a test name equal to the real one, or a host outside
  `TEST_DB_ALLOWED_HOSTS`. An autouse fixture clears the cache around every test.
- **`tests/factories.py`** has `UserFactory`.
- **Tests (34):**
  - the guard: 6 refusals, 6 allowed configurations, and this suite's own settings;
  - isolation: a row and a cache key do not survive into the next test;
  - every factory builds with defaults;
  - a `/api/health/` smoke test;
  - 9 `users.User` tests, which replace the one-off shell check of the 0.1 entry;
  - the 7 `client_ip()` tests, now run by pytest.
- `"typecheck": "tsc --noEmit"` in `frontend/package.json`.
- `AGENTS.md` § 2 and the `/verify` skill now include `uv run pytest` and `npm run typecheck`.

**Why:** `BUILD_ORDER` recommends pulling 2.1 ahead of Phase 1, so the "has tests" criteria in
1.1–1.5 can be met as each lands.
**Files:**
- New: `backend/config/settings_test.py`, `backend/conftest.py`,
  `backend/tests/{__init__,factories,test_factories,test_health}.py`,
  `backend/tests/harness/{__init__,db_guard,test_harness_db_guard,test_harness_isolation}.py`.
- Changed: `backend/users/tests.py`, `backend/pyproject.toml`, `backend/uv.lock`,
  `frontend/package.json`, `AGENTS.md`, `.claude/skills/verify/SKILL.md`, `README.md`,
  `documentation/{DAILY_CHANGES,ONBOARDING}.md`, `documentation/core/ARCHITECTURE.md`,
  `documentation/planning/{BUILD_ORDER,ROADMAP,TECH_DEBT,TESTING_STRATEGY}.md`,
  `documentation/system-design/{DATABASE_MIGRATIONS,DEPLOYMENT,DJANGO_STANDARDS,NEXTJS_STANDARDS}.md`.

**Verification:**
- `uv run pytest`: 34 passed. Inside the backend container, where `CACHE_URL` is the live Redis,
  34 passed and the test settings resolved to `LocMemCache`, so tests never touch the real cache.
- **Positive controls:**
  - a throwaway settings module whose SQLite test file equals its real file made the session stop
    with `ERROR: refusing to test against 'default'…`, exit 4, and the file was never created;
  - deleting the cache-clearing fixture failed `test_state_from_previous_test_is_gone` with
    `'leaked'`. Restored, 34 passed.
- A `TEST_DATABASE_URL` naming a staging Postgres host **could not reach the guard**: `django.setup()`
  fails first because no Postgres driver is installed. Still safe (no database is created), but the
  Postgres path of the guard is covered only by its unit tests until a driver lands.
- `ruff check`: passed. `ruff format --check`: the first run failed on 2 new files (hand-wrapped
  lists); `ruff format` fixed them, and the re-run reports 31 files formatted.
- `manage.py check`: no issues. `makemigrations --check`: no changes. `npm run lint`: clean.
  `npm run typecheck`: clean. Coverage: 99% of 356 statements (measured, no floor set).

**Notes / still open:**
- Not yet:
  - `time-machine` / `frozen_now`, and the outbound-HTTP block (add with the first HTTP client);
  - pytest-xdist;
  - coverage floors, to be set to measured reality later (`TESTING_STRATEGY.md` step 4);
  - frontend Vitest.
- `.claude/settings.json`'s allow-list does not include `uv run pytest` yet, so Claude Code asks
  before running it. It is a protected file; add it if wanted.
- Next in order: 2.2, the architecture tests (route enforcement, migrations, boundaries), then 1.1.

### BUILD_ORDER 1.0: dependencies, cache, client IP, admin switch, Redis in Docker
**What:**
- `pyjwt`, `pyotp`, `cryptography`, `argon2-cffi` and `redis` added with `uv add`
  (`pyproject.toml` and `uv.lock`).
- `settings.py` gains `CACHES` from `CACHE_URL` (LocMem by default), `TRUSTED_PROXY_COUNT`,
  `ADMIN_ENABLED`, `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `FRONTEND_BASE_URL`, Argon2-first
  `PASSWORD_HASHERS`, and `x-csrf-token` in `CORS_ALLOW_HEADERS`.
- `config/urls.py` mounts `/admin/` only when `ADMIN_ENABLED`, which defaults to `DEBUG`.
- New `core/http.py::client_ip()` reads `X-Forwarded-For` from the right, with 7 tests in
  `core/tests.py`.
- `docker-compose.yml` adds a `redis` service and points the backend's `CACHE_URL` at it.
- Every new key is in `backend/.env.example`.

**Why:** `BUILD_ORDER` 1.0, which Phase 1 cannot build without. ADR-0009 plus the owner's
"several servers from day one" make a shared cache a correctness requirement: throttles, lockout
and session liveness live in it (`AUTH_BLUEPRINT.md` § 17.4).
**Files:**
- New: `backend/core/http.py`.
- Changed: `backend/pyproject.toml`, `backend/uv.lock`, `backend/config/settings.py`,
  `backend/config/urls.py`, `backend/core/tests.py`, `backend/.env.example`, `docker-compose.yml`,
  `README.md`, `documentation/{DAILY_CHANGES,ONBOARDING}.md`, `documentation/core/ARCHITECTURE.md`,
  `documentation/planning/{BUILD_ORDER,TECH_DEBT}.md`, `documentation/system-design/DEPLOYMENT.md`.

**Verification:**
- `ruff check`: passed. `ruff format --check`: 21 files formatted. `manage.py check`: no issues.
  `makemigrations --check --dry-run`: no changes.
- `manage.py test core`: 7 tests, OK. **Mutation check:** with `chain[-n]` swapped for the common
  `chain[0]` bug, 2 tests failed (`one_proxy_ignores_a_client_written_prefix`,
  `two_proxies_count_from_the_right`). Restored, all 7 pass.
- Locally, the settings resolve to LocMem, proxy count `0` (int), `ADMIN_ENABLED == DEBUG`, the
  `argon2` hasher, `x-csrf-token` allowed and the console email backend.
- **Acceptance criterion:** inside the backend container, with `CACHE_URL` pointing at Redis,
  `manage.py check` reported no issues. A `cache.set`/`get` round-trip used `RedisCache` and returned
  `pong`. Redis policy is `allkeys-lru`, and port 6379 is not reachable from the host.
- HTTP: `/api/health/` 200, `/admin/` 302 (login redirect, so mounted under `DEBUG`).
- **Unexplained:** one request to `localhost:3000/` returned 302 during the restart. It could not
  be reproduced: five later requests all returned 200 via `127.0.0.1`, Docker is the only listener,
  and the Next.js log shows only 200s.

**Notes / still open:**
- **Dev Redis has no password or persistence.** It is unpublished and on the compose network only.
  The authenticated Redis of `OPERATIONS.md` § 15 is still 4.4 work.
- `client_ip()` is the only reader of `TRUSTED_PROXY_COUNT`. Throttles and lockout must call it,
  never `REMOTE_ADDR`.
- **Not here:** the `dbx.E005` check that refuses LocMem with `DEBUG=False` lands with 1.2a. The
  JWT and cookie keys are 1.1b.
- **Tests:** these run under Django's runner (`manage.py test`). 2.1 adds pytest-django, which
  runs `TestCase` classes unchanged.
- **Your local `backend/.env` needs no change.** Every new key has a safe default. Products set
  `CACHE_URL` and `TRUSTED_PROXY_COUNT` before deploying (`DEPLOYMENT.md` § 1).

### BUILD_ORDER 0.2 decided: JWT in `httpOnly` cookies with DB session rows (ADR-0009)
**What:** The owner settled 0.2 with option C from `AUTH_RND.md`: a JWT access and refresh pair in
`httpOnly` cookies, rotation with reuse detection, and a `users_user_session` row per refresh
token, as `AUTH_BLUEPRINT.md` A4–A5 and Ch. 6 specify. Machine callers use the `API_PLATFORM.md`
§§ 7–8 tokens instead. This is a decision and its docs only; no code changed.
**Why:** `settings.py` configured sessions while the roadmap planned SimpleJWT, so the first
authenticated endpoint would have decided it by accident (DB-1). The owner's answers:
- non-browser callers are likely;
- logout must take effect;
- several servers from day one.

Those rule out pure sessions (a second token system would be needed anyway) and pure stateless JWT
(it cannot be revoked).
**Files:**
- New: `documentation/adr/0009-jwt-in-httponly-cookies.md`.
- Changed: `README.md`, `documentation/{ADR,INDEX,NEW_PROJECT,DAILY_CHANGES}.md`,
  `documentation/core/ARCHITECTURE.md`,
  `documentation/planning/{AUTH_RND,BUILD_ORDER,CORE_ARCHITECTURE_PLAN,ROADMAP,TECH_DEBT}.md`,
  `documentation/system-design/{API_DESIGN,AUTH_BLUEPRINT,SECURITY}.md`.

**Verification:** documentation only, so the code gate was not run. Every relative link in the
changed files resolves (checked by script). `git grep` finds no doc still calling DB-1 open or
planning SimpleJWT, except `AUTH_RND.md`'s option B text and the blueprint's "rejected" table, which
are reasoning.
**Notes / still open:**
- **"Immediate" logout, stated precisely:** a revoked session stops working within
  `SESSION_LIVENESS_CACHE_TTL` (60 seconds) on every server. Setting it to `0` makes revocation
  instant, at one DB read per request. The ADR records the trade.
- Several servers make **Redis mandatory at 1.0**, ahead of the 4.4 Compose work. The Docker dev
  stack will need a Redis service then.
- `settings.py` still sets `SessionAuthentication`. That is intentional until 1.1b. ROADMAP and
  ARCHITECTURE now say so, which meets 0.2's "no longer contradicts" criterion.
- **How a first-party mobile app authenticates is not decided.** The ADR leaves it for its own ADR,
  because `API_PLATFORM.md` § 21 removes the blueprint's Bearer fallback.

### BUILD_ORDER 0.1 decided: a custom `users.User`, email login (ADR-0008)
**What:** The owner settled 0.1. A new `users` app holds `users.User(AbstractBaseUser,
PermissionsMixin)` and its `UserManager`, with the `AUTH_BLUEPRINT.md` § 3.1 columns. Email is the
login, there is no username, `is_active` defaults to `False`, and a check constraint keeps emails
lowercase. `AUTH_USER_MODEL = "users.User"`, and `users/0001_initial` is the project's first
migration. The admin is registered read-mostly: no raw password field, and `is_staff`,
`is_superuser` and `mfa_enforced` are read-only.
**Why:** `AUTH_USER_MODEL` cannot be changed cheaply once any migration refers to it. The owner
picked the blueprint's form (`users.User`, A1–A3) over the older `core.User(AbstractUser)`
recommendation in `DATA_MODEL.md` D1. That one kept a username and put identity in `core`, which
the blueprint keeps free of app models.
**Files:**
- New: `backend/users/{__init__,admin,apps,tests,urls}.py`, `backend/users/models/{__init__,user}.py`,
  `backend/users/migrations/{__init__,0001_initial}.py`,
  `documentation/adr/0008-custom-user-model-email-identity.md`.
- Changed: `backend/config/settings.py` (`INSTALLED_APPS`, `AUTH_USER_MODEL`),
  `backend/config/urls.py`, `backend/pyproject.toml` (`known-first-party`),
  `documentation/{ADR,NEW_PROJECT,ONBOARDING}.md`, `documentation/core/ARCHITECTURE.md`,
  `documentation/planning/{BUILD_ORDER,ROADMAP,TECH_DEBT}.md`,
  `documentation/system-design/{AUTH_BLUEPRINT,DATA_MODEL}.md`, `README.md`.

**Verification:**
- `ruff check`: all checks passed. The first run failed with one E501 on the new model's docstring,
  which was then fixed. `ruff format --check`: 20 files already formatted.
- `manage.py check`: no issues. `makemigrations --check --dry-run`: no changes detected.
- `migrate` on a fresh `db.sqlite3` applied 19 migrations, `users.0001_initial` before `admin.0001`.
- A shell run inside a rolled-back transaction confirmed:
  - `create_user` lowercases and trims the email, and the new user is inactive;
  - `authenticate` returns `None` while the user is inactive and the user once activated;
  - `create_superuser` sets active, staff and superuser;
  - a second account differing only in case raises `IntegrityError`, as does a raw mixed-case
    `UPDATE` (the check constraint);
  - the admin add form validates. 0 rows were left afterwards.

**Notes / still open:**
- The local `db.sqlite3` was deleted and remigrated, with the owner's approval. It held no rows, but
  every existing local database has to be recreated the same way.
- **Deviation from § 3.1, now written into it:** the last-login column stays Django's `last_login`,
  not `last_login_at`. `login()` writes it and the password-reset token hashes it.
- **Not in this change:** the `has_perm` override (`AUTH_BLUEPRINT.md` § 7.4) ships with
  `RBACBackend` and its test in 1.2. `BaseViewSet` waits for the first viewset.
- `DATA_MODEL.md` D2–D5 are still open. They govern later models; `users_user` follows the
  blueprint's A15 (integer PK plus `public_id`).
- `AGENTS.md` § 0 ("know what does not exist yet") was updated with the owner's approval. It now
  says no *production* Docker and names `users.User` as the only model.

### Docker development stack — both apps, live reload
**What:** `docker compose up --build` runs Django (`runserver`) and Next.js (`next dev`) in
containers. Source is bind-mounted, both reload on save, logs stream to the terminal, and
migrations run on start. The stack uses `backend/Dockerfile.dev`, `frontend/Dockerfile.dev`, their
`.dockerignore` files and a root `docker-compose.yml`. `src/lib/api.ts` now sends server-side
requests to `INTERNAL_API_URL` when it is set.
**Why:** The owner wants to watch the app continuously while building. This is the development half
of `BUILD_ORDER` 4.4. It uses SQLite per ADR-0005, so no Postgres driver, protected-file edit or
superseding ADR is needed yet.
**Files:**
- New: `docker-compose.yml`, `backend/Dockerfile.dev`, `backend/.dockerignore`,
  `frontend/Dockerfile.dev`, `frontend/.dockerignore`.
- Changed: `frontend/src/lib/api.ts`, `frontend/.env.example`,
  `documentation/system-design/{NEXTJS_STANDARDS,DEPLOYMENT}.md`, plus the README, ONBOARDING,
  ARCHITECTURE, ROADMAP and BUILD_ORDER (4.4) lines shared with the entry above.

**Verification:**
- `docker compose config --quiet` passed, and both images built.
- `docker compose up -d --build`: backend and frontend both `healthy`.
- `curl localhost:8000/api/health/` returned `{"status":"ok",…,"database":true}`, and
  `localhost:3000` rendered the health box as ok. That shows the server-side fetch reached
  `http://backend:8000`.
- Live reload:
  - a temporary marker in `page.tsx` appeared on the next request, and the file was then restored
    with `git checkout`;
  - `touch core/views.py` logged `changed, reloading`.
- `npm run lint`: clean. `npx tsc --noEmit`: clean.

**Notes / still open:**
- **Hardening applied:** ports bound to `127.0.0.1`, non-root uid 1000 in both images,
  `no-new-privileges` and `cap_drop: [ALL]` (`OPERATIONS.md` § 15). The virtualenv (`/opt/venv`),
  `node_modules` and `.next` live outside the bind mount, so the host's macOS binaries are never
  used.
- **Gotcha:** `node_modules` is an anonymous volume. After a dependency change, run `up --build -V`,
  or the old modules persist.
- `backend/db.sqlite3` is shared with a host `runserver`. Run one or the other on port 8000, not
  both.
- **Still for 4.4:** Postgres, Redis, the `OPERATIONS.md` § 1 project naming, and the remaining § 15
  hygiene (log driver, resource limits). Base images are pinned to minor tags, not digests.

### Fix `attribution` in `.claude/settings.json`: string values, not booleans
**What:** `attribution.commit` and `attribution.pr` changed from `false` to `""`.
**Why:** Claude Code types both keys as strings, where the value is the text appended and an empty string
disables it. With booleans, Claude Code rejected the settings at startup ("Expected string, but received
boolean") and dropped the values. Attribution was never actually turned off, and Claude Code kept prompting
for a `Co-Authored-By` trailer that only the `agent_guard.py` commit check caught.
**Files:** `.claude/settings.json`, `documentation/DAILY_CHANGES.md`.
**Verification:** the settings file parses as JSON, with `attribution = {'commit': '', 'pr': ''}`;
`python3 .claude/hooks/test_agent_guard.py` ran 18 tests, OK.
**Notes:** `AGENT_TOOLING.md` and ADR-0007 say "attribution off" without naming a value, so they still hold.

---

## 2026-10-07

### Agent tooling: `.claude/` guard rails, skills and subagents; a contract under budget
**What:** Added a Claude Code harness following the official `.claude` directory layout:
- `.claude/settings.json`: attribution off, the § 2 gate allow-listed, and `.env` reads denied.
- Two hooks: `agent_guard.py` (PreToolUse) and `session_context.py` (SessionStart), plus a stdlib self-test.
- Five pointer-only path-scoped rules.
- Seven skills: `/verify`, `/changelog`, `/commit`, `/next-task`, `/adr`, `/bug-class-check` and
  `/new-django-app`.
- Three subagents: `code-reviewer`, `doc-auditor` and `implementer`. The first two have committed memory.
- `.worktreeinclude` and `GEMINI.md`, which imports `AGENTS.md`.

`AGENTS.md` went from 240 to 198 lines with every rule kept: procedures moved to skills, and § 7 was rewritten
as "Agents and tooling". The protected list gained `GEMINI.md` and `.claude/settings.json`, and rule 7 gained
`.claude/settings.local.json`. The decision is recorded as ADR-0007, and the subsystem is documented in
`core/AGENT_TOOLING.md`.

**Why:** Every rule depended on the agent remembering it. `CLAUDE.md`/`AGENTS.md` are context, not
enforcement, and the contract exceeded the documented ~200-line adherence budget. The owner's choices
(2026-10-07):
- `.claude/rules/` holds pointers only, which keeps ADR-0006 intact and Codex, Cursor and Copilot on the
  full rule set.
- Protected-file edits **ask** rather than refuse.
- The guard refuses malformed or AI-attributed commit messages and history rewriting. Bulk staging and
  plain pushes are not refused.
- A `GEMINI.md` pointer is added. No other per-tool files.

This resolves `ENGINEERING_PRACTICES.md` pending decision 6.

**Files:**
- New: `.claude/settings.json`, `.claude/hooks/{agent_guard,session_context,test_agent_guard}.py`,
  `.claude/rules/{backend,migrations,frontend,documentation,agent-config}.md`,
  `.claude/skills/{verify,changelog,commit,next-task,adr,bug-class-check,new-django-app}/SKILL.md`,
  `.claude/agents/{code-reviewer,doc-auditor,implementer}.md`,
  `.claude/agent-memory/{code-reviewer,doc-auditor}/MEMORY.md`, `.worktreeinclude`, `GEMINI.md`,
  `documentation/adr/0007-claude-code-harness.md`, `documentation/core/AGENT_TOOLING.md`.
- Edited: `AGENTS.md`, `.gitignore`, `documentation/{ADR,INDEX,DAILY_CHANGES}.md`,
  `documentation/planning/ROADMAP.md`, `documentation/system-design/ENGINEERING_PRACTICES.md` (pending
  decision 6 marked decided).

**Verification:**
- `python3 .claude/hooks/test_agent_guard.py`: 18 tests, OK. The run includes the guard parsing the rewritten
  `AGENTS.md` protected list (14 entries) and the commit types.
- `session_context.py` run by hand printed the branch, the dirty files, django 5.2.17 / DRF 3.18.1 / next
  16.3.4 / react 19.2.8, and the next task (0.1 🚧 DECISION).
- `settings.json` parses as JSON, and every `.claude/**` frontmatter block parses as YAML.
- A link-and-anchor check over `documentation/**`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and
  `.claude/**` found 0 problems. Every path cited in `.claude/**` exists, except the gitignored
  `settings.local.json`, by design.
- A name and secret scan of every changed file found 0 hits. `AGENTS.md` is 198 lines.
- **Not verified live:** hooks register at session start, so this session could not exercise them. A probe
  `git commit -m "Updated stuff"` reached git, which refused it only because nothing was staged.
- The § 2 code gate was not run, because no backend or frontend code changed.

**Notes / still open:**
- Hooks load at session start. Run `/hooks` in a new session to confirm they registered.
- Enforcement is Claude Code only. Other agents get the same written rules.
- The `CLAUDE.md` maintainer comment still says the import is "the ONLY thing that loads automatically",
  which is no longer true now that `.claude/rules/` and skill descriptions exist. It is a protected file and
  was left unedited. The comment is stripped from context, so the stale text costs nothing at runtime.
- A `commit-msg` git hook for humans (`ENGINEERING_PRACTICES.md` § 39) is still future work.

---

## 2026-09-29

### The platform blueprint — every capability a strong base needs, specified
**What:** Added the master capability map `planning/PLATFORM_BLUEPRINT.md` and fourteen specification
documents under `system-design/` (~20,000 lines in total). The specs cover configuration, extensibility, the
API platform, jobs and integrations, notifications and alerting, observability, operations, the frontend
platform, data lifecycle, domain primitives, optional modules, the bug-class register, engineering practices
and a lessons catalogue. `BUILD_ORDER.md` gains Phases 5–9 (platform services, each task with acceptance
criteria); the old Phase 5 is now Phase 10. `VISION.md` gains principle 7, *"Nothing hard-coded — a product,
not a college project"*, and its two related non-goals are clarified. `ROADMAP.md` and `INDEX.md` list the new
specs. `TECH_DEBT.md` gains DB-18 – DB-31.

**Why:** The repository owner's brief: a base that any large product (ERP, CRM, e-commerce, anything) can be
built on from day one — reliable, powerful, nothing hard-coded. Several mature production codebases from
different domains were studied read-only (~450 findings), and every mechanism worth having was written down
as a pattern with the failure it prevents. Per `AGENTS.md` rule 5a no source is named anywhere; each spec
carries a *Blueprint — nothing built yet* banner.

**Found while doing it (now in `TECH_DEBT.md`), each verified against the installed code:**
- **DB-30** — today's `AnonRateThrottle` runs with DRF `NUM_PROXIES` unset, so DRF keys it on the whole
  client-supplied `X-Forwarded-For` header and the limit is bypassable. The same block pins no renderer or
  parser classes.
- **DB-25** — the documented `get_random_secret_key()` recipe can produce a key starting with `$`, which
  django-environ reads as a reference to another variable.
- **DB-31** — DRF answers 403, not 401, when the authenticator has no `authenticate_header()`; the planned
  "refresh on 401" client contract would never fire.
- **DB-26** — `AUTH_BLUEPRINT.md` puts `__Host-` on a cookie scoped to `Path=/api/`; browsers reject that.
- **DB-18 – DB-24, DB-27 – DB-29** — spec contradictions and gaps: the plugin-import swallow, system checks not
  running under gunicorn, cookie paths invisible to page navigations, the machine-caller model, the
  `PUBLIC_ROUTES` seam, the tenancy evidence, the API prefix, DB-11's inaccurate description, the Turbopack
  root, and SQLite ignoring `select_for_update()`.

**Files:** `planning/PLATFORM_BLUEPRINT.md` (new); `system-design/{CONFIGURATION, EXTENSIBILITY, API_PLATFORM,
JOBS_AND_INTEGRATIONS, NOTIFICATIONS_AND_ALERTING, OBSERVABILITY, OPERATIONS, FRONTEND_PLATFORM,
DATA_LIFECYCLE, DOMAIN_PRIMITIVES, REUSABLE_MODULES, BUG_CLASSES, ENGINEERING_PRACTICES, LESSONS_LEARNED}.md`
(new); `VISION.md`, `INDEX.md`, `planning/BUILD_ORDER.md`, `planning/ROADMAP.md`, `planning/TECH_DEBT.md`.

**Verification:** documentation only; no code changed. A scan for source names, ticket numbers and
market-specific literals found none in the new or edited files. A link-and-anchor check over every `.md` in
`documentation/`, `README.md` and `AGENTS.md` found no broken links (the one hit is the ADR template's
deliberate `NNNN-….md` placeholder). The `AGENTS.md` § 2 code gate was not run, because no code changed.

**Still open:**
- Each spec ends with *Pending decisions* for the owner. The cross-cutting ones are in `PLATFORM_BLUEPRINT.md`
  § 5 and § 6.
- `ENGINEERING_PRACTICES.md` proposes `AGENTS.md` additions (worktree protocol, the diff is the verdict,
  autospec mocks, the bug-class trigger, a Field Notes table). They await approval, because `AGENTS.md` is a
  protected file. Several specs also propose edits to protected files (`backend/pyproject.toml`,
  `frontend/next.config.ts`, and the `config/settings.py` split); none were made.
- The existing docs each spec lists under *⚠️ Conflicts* were deliberately **not** edited; they are resolved
  task by task per `BUILD_ORDER.md`.

---

## 2026-09-21

### Design review of the auth/authz/RBAC blueprint — 28 gaps found and closed
**What:** Reviewed `AUTH_BLUEPRINT.md` chapters 1–15 as a system design, before writing any code,
and closed everything it found. The document goes from 1,435 to ~2,100 lines: five new chapters
(16 runtime dependencies · 17 the deployment contract · 18 outbound email · 19 bootstrap and
operations · 20 the Django admin), seven new decisions **A19–A25**, four new system checks
`dbx.E005`–`E008`, and Appendix B recording what the review found. Three `BUILD_ORDER` tasks added:
**1.0** (dependencies + deployment contract, ahead of everything else in Phase 1), **1.5b** (email
and `bootstrap_admin`) and **1.7** (retention, key rotation, the admin decision).

**Why:** Four of the gaps were defects that make the spec unbuildable as written, and each was
verified against the installed Django 5.2.17 source rather than argued from memory:

1. `PermissionsMixin.has_perm` returns `True` for an active superuser **before any backend runs**
   (`django/contrib/auth/models.py:77-78`), so decision A12's audited bypass was unreachable and
   `authz.superuser_bypass` would never have been written — while Ch. 9.5 claimed it always is. An
   audit guarantee that is silently false is worse than none, because the empty log reads as "no
   bypasses happened". Fixed by overriding `has_perm` on `users.User`.
2. `ModelBackend` rejects inactive users inside `authenticate()`
   (`django/contrib/auth/backends.py:91-96`), so login step 5 was unreachable and
   `failure_reason="inactive"` could never be recorded. With `is_active` defaulting to `False`,
   every invited user's first login would have been filed as `bad_password`. Fixed by
   authenticating through `AllowAllUsersModelBackend` and gating explicitly.
3. The system-role migration runs before `post_migrate`, so `administrator` would have been seeded
   holding **no** permissions. Fixed by splitting rows from grants.
4. Two documented routes address a `public_id` column their tables did not have.

The rest were missing pieces without which the system does not work end to end — no dependency list
at all (nothing in Ch. 16 is installed); refresh rotation with no grace window, which logs a
two-tab user out for using the product normally; no cache configuration, leaving three security
controls silently per-worker; client IP from `REMOTE_ADDR`, which turns per-IP lockout into a
self-inflicted outage behind any proxy; no same-site/CORS statement, so the cookie scheme works in
dev and fails silently across domains; forgeable CSRF double-submit; TOTP with no replay guard; no
email configuration for the two flows that send mail; no way to create the first account; and the
Django admin as an unmentioned second authentication *and* authorization system that bypasses every
guard in Ch. 8.

**Files:** `documentation/system-design/AUTH_BLUEPRINT.md`, `documentation/system-design/RBAC_DESIGN.md`,
`documentation/planning/BUILD_ORDER.md`, `documentation/planning/TECH_DEBT.md` (DB-15, DB-16, DB-17),
plus rule-5a cleanup in `documentation/system-design/{API_DESIGN,DATA_MODEL}.md`,
`documentation/planning/TESTING_STRATEGY.md` and this file.

**Verification:** Docs only — no code changed. `ruff check` and `ruff format --check` clean;
`manage.py check` reports no issues; `makemigrations --check --dry-run` clean (no model changes).
Django behaviours 1 and 2 above were read out of `backend/.venv/.../django/contrib/auth/` in this
session, not recalled. All relative links in the edited files resolve.

**Notes:** `RBAC_DESIGN.md` and `AUTH_BLUEPRINT.md` disagreed about the seeded roles — `admin` vs
`administrator`, and `staff` as "read everything" vs nothing. One seeder, two specifications.
`administrator` and "nothing" win; a default role that can read every row is the object-scoping bug
with a reassuring name. The two 🚧 decisions (`0.1`, `0.2`) are still open and still the owner's.

### No other codebase is named anywhere in this repository
**What:** Removed every reference to other projects, products and modules from the working tree —
147 hits across 17 files. The reasoning they supported was kept and rewritten to stand on its own;
only the attribution is gone. Added `AGENTS.md` rule **5a** so it cannot creep back. The project no
longer describes itself as a sibling of anything: `README.md`, `AGENTS.md`, `CLAUDE.md` and
`ONBOARDING.md` now call it a Django + Next.js base project, and the two "parity" tables in
`README.md` and `ROADMAP.md` became plain capability tables. Example plugin names in
`CORE_ARCHITECTURE_PLAN.md`, `PLUGIN_DEVELOPMENT.md`, `DATA_MODEL.md` and `RBAC_DESIGN.md` are now
the generic `billing`.
**Why:** The owner's call: this repository is public and is copied into other repositories, so its
history should not record which codebases its design was informed by. Rule 5 already forbade
client names and internal URLs; 5a extends the same reasoning to any other codebase, for the same
reason — a name committed here is inherited by every product copied from it, long after anyone
remembers why it was there.
**Files:** `README.md`, `AGENTS.md`, `CLAUDE.md`, `backend/core/views.py`,
`documentation/{INDEX,ONBOARDING,DAILY_CHANGES}.md`,
`documentation/adr/{0002-api-first-drf-not-django-templates,0006-one-agent-contract}.md`,
`documentation/planning/{AUTH_RND,ROADMAP,TESTING_STRATEGY,PLUGIN_DEVELOPMENT,CORE_ARCHITECTURE_PLAN}.md`,
`documentation/system-design/{AUTH_BLUEPRINT,DATA_MODEL,RBAC_DESIGN}.md`.
**Verification:** A case-insensitive sweep of the whole working tree — every file type, not only
markdown, excluding `.git/` and `node_modules/` — returns **zero matches** for any of the removed
names. Every relative markdown link in the repository resolves; the only reported miss is the
`NNNN-….md` placeholder inside `adr/0000-template.md`, which is intentional. One Python file
changed (a docstring), so the § 2 gate was run in full: `ruff check` passed, `ruff format --check`
reported 13 files already formatted, `manage.py check` found no issues, and
`makemigrations --check --dry-run` detected no changes.
**Notes:** **History was rewritten too.** The working-tree fix alone would have left the names fully
readable in the five earlier commits already on the remote, so after the cleanup landed, all six
commits were rewritten with `git filter-branch` (file contents *and* commit messages) and
force-pushed. Every commit hash changed — the initial scaffold is now `cac0491`. A full mirror plus
a working-tree archive were taken first, to `~/djangobasex-backup-20260921-055737/`. Verified by
cloning the remote fresh and sweeping every commit and every message: zero matches.
⚠️ **Two limits remain, and neither is fixable from here.** Any clone or fork taken before the
rewrite still holds the old objects, and the host may keep unreferenced objects reachable by their
SHA for some time. What is gone is gone from the repository; it is not recalled from anyone who
already had it.
The auth research this design came from was moved out of the repository entirely rather than
anonymised in place — its substance now lives in `system-design/AUTH_FAILURE_MODES.md`, written as
a failure catalogue that needs no sources, because a failure mode is true or false on its own and
citing where it was observed adds nothing a reader can use.

### Auth, authorization and RBAC — design spec
**What:** Added two documents under `documentation/system-design/`.
`AUTH_FAILURE_MODES.md` (282 lines) catalogues the seventeen ways auth and RBAC systems fail —
the forgotten gate, the permission that does not exist, Layer 1 without Layer 2, implicit
route→permission resolution, revocation that is not revocation, and so on — each with how it
presents and what defends against it, plus a design checklist and four rules for the tooling
itself. `AUTH_BLUEPRINT.md` (1,420 lines, 15 chapters) is the build spec: 18 decisions with their
reversal costs; the three-app split (`core`/`users`/`rbac`); all 14 tables with every column, type,
index, constraint and foreign key; the ER map and an `on_delete` rationale; the full file tree; the
authentication flows; the authorization engine; RBAC roles and seeding; the fail-closed machinery;
the API surface; the frontend contract; settings; migration order; the test plan; and a build
sequence mapping each `BUILD_ORDER` Phase 1 task to its chapters. Cross-linked from `INDEX.md`,
`RBAC_DESIGN.md` and `BUILD_ORDER.md` § Phase 1.
**Why:** So that starting to code means opening the blueprint and typing, rather than designing at
the keyboard. The failure catalogue is separate on purpose: a spec that only says *what* to build
gets argued with, and the arguments are always about cost. Naming the failure each decision buys
protection from is what makes it possible to reopen one on the merits later instead of guessing
what it was protecting against.
**Files:** `documentation/system-design/AUTH_FAILURE_MODES.md`,
`documentation/system-design/AUTH_BLUEPRINT.md`, `documentation/INDEX.md`,
`documentation/system-design/RBAC_DESIGN.md`, `documentation/planning/BUILD_ORDER.md`.
**Verification:** Docs only — no code changed, so the `AGENTS.md` § 2 gate does not apply. All
relative links in both documents resolve; the blueprint's 15 chapter anchors match their heading
text. Checked for contradictions against the docs they must agree with: base model classes and the
`visible_to()` scoping rule come from `DATA_MODEL.md` §§ 2 and 5; the error shape, the 404-not-403
rule for invisible rows, pagination and the machine-caller posture from `API_DESIGN.md`; the
URL→view→service→model layering and the new-app checklist from `DJANGO_STANDARDS.md`; the
four-concept model, grant-only rule and frontend posture from `RBAC_DESIGN.md`. No second way of
doing anything was introduced.
**Notes:** Two `BUILD_ORDER` 🚧 decisions (`0.1` custom user, `0.2` auth model) remain the owner's
and are **not** decided — they are written as stated assumptions A1–A5 with their reversal costs,
and Chapter 13 says what has to restart if either flips. Chapter 9 is the part that makes this
stronger rather than merely complete: default-deny on the base viewset, so omitting a gate denies
instead of serves; system checks `dbx.E001`–`E004` that fail `manage.py check` — already in the § 2
gate — when a route declares no permission or names a code absent from the catalog; the
route-enforcement test; and a permissions doctor. Each turns a discipline into a mechanism, because
discipline does not survive scale, turnover or a deadline. Two deliberate trades are written down
rather than left to be discovered: session liveness is cached 60s, so revocation takes effect
within a minute rather than instantly; and the superuser bypass is kept but audited on every use,
because a bypass held by the people most likely to test a feature hides breakage from the people
most able to fix it.

### Build order resequenced — authentication, authorization, RBAC first
**What:** Reordered `BUILD_ORDER.md` on the repository owner's instruction: the platform now leads
and the tooling follows. The two 🚧 DECISION items became **Phase 0** (they gate the first
migration, so they cannot follow the auth work that writes it); authentication → authorization →
RBAC → Users CRUD → `core`/`project` split became **Phase 1**; the old Phase 0 (test stack,
architecture tests, CI) became **Phase 2**; plugins, reusability and the second-product test shifted
to Phases 3–5. Split the old single "RBAC" task into **1.2 Authorization** (the `Permission` models,
the code-declared catalog, `HasPermission` for Layer 1 and `visible_to()` for Layer 2) and **1.4
RBAC** (`Role`/`UserRole`, the seeded system roles, `/me` permission codes, the roles screen last),
which is the owner's stated authorization-then-RBAC order and also `RBAC_DESIGN.md`'s own build
order. Added a new "The order, and why it is this one" section recording the decision, its date and
its cost.
**Why:** Asked for by the repository owner. The previous order put enforcement tooling first on the
argument that no convention is real until something can fail a build; the owner's call is that the
platform is worth more first. Both are defensible and the decision is the owner's — but reordering
silently would leave the next reader unable to tell a deliberate sequence from an accidental one,
which is why the reason is now in the file.
**Files:** `documentation/planning/BUILD_ORDER.md`, `documentation/system-design/DATA_MODEL.md`.
**Verification:** Docs only — no code changed, so the `AGENTS.md` § 2 gate does not apply. Checked
every cross-reference to the file: `DATA_MODEL.md` § D1 said "`BUILD_ORDER` task 1.1" for the custom
user model and now says 0.1. The "Phase 0" mentions in `README.md`, `NEW_PROJECT.md`,
`UPGRADING.md` and `PLUGIN_DEVELOPMENT.md` refer to `CORE_ARCHITECTURE_PLAN.md`'s own phases, not
this file's, and were correctly left alone. `AGENTS.md` § 0 (start at the lowest unfinished task;
two tasks are 🚧) and `INDEX.md` still hold without edits. Relative links in the rewritten file
resolve.
**Notes:** The cost of the trade is written into the file rather than resolved quietly. Several
Phase 1 acceptance criteria say "and has tests" or name `test_route_enforcement.py`, and neither can
be satisfied until **2.1** installs `pytest`. The file recommends pulling 2.1 forward on its own —
it is a dependency-and-config task, not a feature — while leaving the choice with the owner. Already
tracked as `TECH_DEBT` **DB-5**/**DB-6**; no new debt row was added. Earlier entries in this log
that cite old task numbers (the 2026-09-16 entry's "task 1.1") were left as written — this is a
historical log, not a current-state doc.

## 2026-09-16

### System design completed — vision, data model, RBAC, API, security
**What:** Added `VISION.md` (what the project is for, the three properties in priority order, the
design principles, success criteria, and explicit non-goals) and four system-design documents:
`DATA_MODEL.md`, `RBAC_DESIGN.md`, `API_DESIGN.md`, `SECURITY.md`. Wired all five into `INDEX.md`,
`AGENTS.md` § 6, `README.md` and `BUILD_ORDER.md`.
**Why:** The docs covered *how to work* (standards, contract) and *what to build* (backlog) but not
*what the system is*. Those four are the parts that are brutal to retrofit: the schema, the
authorization model and the API contract all get fixed by the first module that touches them.
**Files:** `documentation/VISION.md`,
`documentation/system-design/{DATA_MODEL,RBAC_DESIGN,API_DESIGN,SECURITY}.md`,
`documentation/INDEX.md`, `documentation/planning/BUILD_ORDER.md`, `AGENTS.md`, `README.md`.
**Verification:** Docs only. All relative links across the repository resolve. Existing settings
claims re-checked against `backend/config/settings.py`.
**Notes:** `DATA_MODEL.md` § 1 raises **five decisions that must be ADRs before the first
migration** — custom `User`, primary key type, multi-tenancy, soft delete, change history. D1 and D3
are the expensive ones: `AUTH_USER_MODEL` cannot be changed cheaply once referenced, and retrofitting
tenancy is a rewrite rather than a migration. `BUILD_ORDER.md` task 1.1 now points at all five.
The recommendation on D3 is deliberately "no organisation model, but scope through
`visible_to()` from module one" — so adding tenancy later is one method per model, not every view.

### README rewritten, and an executable backlog added
**What:** Rewrote `README.md` against the current state — Documentation, Architecture, Project
Status, Using This As A Core and Contributing sections, an updated folder tree and table of
contents. Added `documentation/planning/BUILD_ORDER.md`: numbered tasks in dependency order, each
with acceptance criteria, across four phases. Wired it into `INDEX.md` and `AGENTS.md` §§ 0 and 6.
**Why:** The README was still the initial scaffold's and described none of the architecture, so the
repository's entry point understated it. And the plans said *what* to build without saying what to
do first or how to know a task was finished — which is the difference between a document an agent
can read and one it can execute.
**Files:** `README.md`, `documentation/planning/BUILD_ORDER.md`, `documentation/INDEX.md`,
`AGENTS.md`.
**Verification:** Docs only. All relative links across `README.md`, `AGENTS.md`, `CLAUDE.md` and
`documentation/**` resolve; README's table-of-contents anchors all match real headings. Audited every
doc for wrong-stack leakage (FastAPI, Alembic, Laravel, Composer).
**Notes:** `BUILD_ORDER.md` marks two tasks 🚧 DECISION — the custom `User` model and the auth model.
`AGENTS.md` § 0 now tells an agent arriving with no task to start at the lowest unfinished item and
to **ask** rather than answer a 🚧 by starting to code. Both are ordered first because both are
settled by accident otherwise, and `AUTH_USER_MODEL` in particular must be fixed before any
migration references it.

### Reusability, plugin and testing docs
**What:** Added `NEW_PROJECT.md` (clone-and-re-origin, the rename checklist, the decisions to settle
first), `UPGRADING.md` (how a product takes a core update, and what a conflict tells you),
`planning/PLUGIN_DEVELOPMENT.md` (the plugin contract, five enforced rules, the outside-contributor
sandbox branch), `planning/AUTH_RND.md` (session vs JWT — resolves DB-1) and
`planning/TESTING_STRATEGY.md` (the four tests to write first, coverage floors, CI shape).
**Why:** `CORE_ARCHITECTURE_PLAN.md` describes the design; these describe how a person actually uses
it — copying the boilerplate, taking updates, owning a plugin — plus the two gaps that block real
work: the undecided auth model and the absent test suite.
**Files:** `documentation/NEW_PROJECT.md`, `documentation/UPGRADING.md`,
`documentation/planning/{PLUGIN_DEVELOPMENT,AUTH_RND,TESTING_STRATEGY}.md`, `documentation/INDEX.md`.
**Verification:** Docs only. Relative links checked; none broken.
**Notes:** `AUTH_RND.md` recommends JWT in `httpOnly` cookies but explicitly says staying with
sessions is a respectable end state. It is a
recommendation, not a decision; the decision is still the owner's and still open.

## 2026-09-15

### Agent contract and documentation structure
**What:** Added the root `AGENTS.md` operating contract and `CLAUDE.md` entry point, plus this
`documentation/` tree — INDEX, ADR register with six records, architecture, Django and Next.js
standards, migrations, deployment, roadmap and tech debt.
**Why:** DjangoBaseX is a boilerplate, so its conventions are inherited by every product copied from
it. Nothing recorded them, and AI agents working in the repo had no contract at all. The structure
was adapted from an earlier core on a different stack and rewritten against this one — the original
was FastAPI/Alembic and its instructions would not have applied here.
**Files:** `AGENTS.md`, `CLAUDE.md`, `documentation/**`.
**Verification:** Documentation only — no code changed, so the § 2 gate was not applicable. Every
factual claim was read out of `backend/config/settings.py`, `backend/pyproject.toml` and
`frontend/package.json` rather than assumed.
**Notes:** The auth model is deliberately left open rather than invented (`TECH_DEBT` DB-1) — it is
the repository owner's call and settling it by accident is the failure to avoid.

### Core architecture plan — plugins and reusability
**What:** Added `documentation/planning/CORE_ARCHITECTURE_PLAN.md`: the design for a three-layer
core (`core/` · `project/` · `plugins/`), a boot-time registry seam, git-submodule plugins holding
both their backend and frontend halves, and the checks that enforce every boundary.
**Why:** DjangoBaseX should be copyable into a new project and extended by independent teams in their
own repos. The design combines a reusability mechanism (core/project split, SHA manifest,
clone-and-re-origin) with a parallel-team mechanism (one repo per plugin, prefixed namespaces, no
cross-plugin imports).
**Files:** `documentation/planning/CORE_ARCHITECTURE_PLAN.md`.
**Verification:** Plan only — no code written. Every mechanism described was read out of a working
implementation rather than recalled. Relative links checked; none broken.
**Notes:** Decisions taken: seams before features · plugins hold both halves · git submodules.
One deliberate divergence from the usual arrangement — plugin docs live in the plugin repo, not
centrally, because separate teams should not route doc changes through the core's review queue.

### Commit attribution decided
**What:** `AGENTS.md` § 4 now forbids AI attribution in commit messages, replacing the note that
left it open.
**Why:** Asked and answered by the repository owner. A permanent public history should not carry
trailers naming a tool that will outlive its relevance.
