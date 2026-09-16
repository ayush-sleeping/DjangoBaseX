# Build Order

**The executable backlog.** [`ROADMAP.md`](ROADMAP.md) says *what* DjangoBaseX will have;
this says *what to do next, in what order, and how to know it is done*.

**If you are an agent picking this project up cold, this is your task list.** Read
[`../../AGENTS.md`](../../AGENTS.md) first for the rules, then start at the lowest-numbered
unfinished task.

---

## How to use this

1. **Work top to bottom.** The order is dependency order, not preference — each task is materially
   harder to do well before the one above it
2. **One task per branch, one task per PR.** Do not batch
3. **A task is done when its acceptance criteria pass** — not when the code is written
4. **Run the gate** (`AGENTS.md` § 2) and log in `DAILY_CHANGES.md` before calling anything complete
5. **Tick the box here in the same PR.** An un-ticked completed task means the next person redoes it

> ⚠️ **Two tasks below are marked 🚧 DECISION.** They are not implementation work — they are
> questions only the repository owner can answer. **Do not start the task after a 🚧 until the
> decision is recorded as an ADR.** Both get settled by accident if someone just starts coding, and
> both are expensive to reverse.

---

## Phase 0 — make the rules enforceable

*Nothing in this repository can currently fail a build. Until that changes, every convention is
advisory and every later phase is built on trust.*

### 0.1 — Install the test stack ⬜
Add `pytest`, `pytest-django`, `factory_boy`, `pytest-cov` to the `dev` dependency group in
`backend/pyproject.toml`. Add `pytest.ini_options` to `pyproject.toml` with `DJANGO_SETTINGS_MODULE`.
Add `"typecheck": "tsc --noEmit"` to `frontend/package.json` (closes `TECH_DEBT` **DB-2**).

**Done when:** `cd backend && uv run pytest` runs and reports at least one passing smoke test that
hits `/api/health/`. `cd frontend && npm run typecheck` passes.

### 0.2 — The architecture tests ⬜
In `backend/tests/architecture/`, per [`TESTING_STRATEGY.md`](TESTING_STRATEGY.md) § "The four tests":

- `test_route_enforcement.py` — walk Django's URL resolver for **every** route, call each
  unauthenticated, fail on anything that is not 401/403. **A 404 counts as a failure** — it means the
  handler ran a lookup before checking who was asking
- `test_migrations.py` — one migration head per app, and every model has a table

**Done when:** both pass, and deliberately breaking one (open a view with `AllowAny`, branch a
migration) makes the right test fail with a readable message.

### 0.3 — CI ⬜
`.github/workflows/ci.yml`, **two jobs** so a Python failure still reports the TypeScript result:
backend (`ruff check` · `ruff format --check` · `manage.py check` · `makemigrations --check
--dry-run` · `pytest`) and frontend (`npm ci` · `lint` · `typecheck` · `next build`).

Run the backend job against a **PostgreSQL 16 service**, not SQLite — a suite proving behaviour
against a database nobody deploys proves it in the wrong place.

**No `continue-on-error` on any step.** A non-blocking check is a check nobody reads.
Closes **DB-5** / **DB-6**.

**Done when:** a PR with a deliberate lint error goes red, and a clean PR goes green.

---

## Phase 1 — the platform

### 1.1 — 🚧 DECISION: custom `User` model or Django's ⬜
**This is first for a reason.** `AUTH_USER_MODEL` must be settled **before any migration references
it**. Swapping later is one of Django's genuinely painful migrations.

Answer even if the answer is "the default is fine" — an unrecorded default is not a decision.
Recommendation: **add a custom user model now** (`core.User` subclassing `AbstractUser`), because it
costs nothing today and is very expensive to add at product three. Closes **DB-10**.

**Done when:** an ADR exists, and if a custom model was chosen, `AUTH_USER_MODEL` is set and migrated
before anything else.

### 1.2 — 🚧 DECISION: the auth model ⬜
Read [`AUTH_RND.md`](AUTH_RND.md), answer its four questions, pick session / JWT / JWT-in-cookies,
write the ADR. Closes **DB-1**.

**Done when:** the ADR is Accepted and `ROADMAP.md` no longer contradicts `config/settings.py`.

### 1.3 — Authentication ⬜
Implement what 1.2 decided: register, login, logout, `/me`, password reset, and the frontend half in
`src/lib/api.ts`.

⚠️ **If the decision was any cookie-based scheme:** an `httpOnly` cookie **cannot be forwarded from a
Next.js server component**, so authenticated data must be fetched client-side and public data
server-side. Getting these backwards **fails silently**. Write the rule into `NEXTJS_STANDARDS.md`
in this same PR.

**Done when:** `test_route_enforcement.py` still passes, a login round-trip is tested (anonymous 401
→ sign in → recognised → sign out → 401), and a wrong password and an unknown address answer
**identically** (no user enumeration).

### 1.4 — The registry seam ⬜
`backend/core/registry.py` per [`CORE_ARCHITECTURE_PLAN.md`](CORE_ARCHITECTURE_PLAN.md) § 2 —
permissions, navigation, api_routes, events, jobs, search, settings, health. Registration is
boot-time, one-way, read-only afterwards. **`registry.py` imports nothing from `core`.**

**Done when:** a throwaway app registering a permission group and a nav section appears in both
without any core file naming it.

### 1.5 — RBAC ⬜
Roles and permissions **through the registry**, not a hard-coded catalog. Permission names are
`<module>.<feature>.<action>`. Fail closed, matching DRF's existing `IsAuthenticated` default.

**Done when:** a user with a role holding no permissions is refused by every gated endpoint, and the
catalog is assembled from registrations rather than a literal.

### 1.6 — Users CRUD ⬜
The reference module every later module copies. Backend viewset + serializers + services; frontend
list, detail, create, edit. Follow `DJANGO_STANDARDS.md` § 3 layering exactly — this one is the
template, so shortcuts here get copied forever.

**Done when:** full CRUD works end to end, is permission-gated, is paginated, and has tests.

### 1.7 — `core/` vs `project/` split ⬜
Split the backend into `core/` (platform) and `project/` (product) with `config/` as composition
root; mirror on the frontend. Add the boundary tests: `core/` must not import `project`, and
`frontend/src/core/` must not import `src/project/`.

**Done when:** deleting `project/` leaves a working platform, and a test asserts it.

---

## Phase 2 — the plugin system

### 2.1 — Plugin discovery ⬜
`backend/core/plugins.py` — scan `backend/plugins/*/plugin.toml`, add to `sys.path`, append to
`INSTALLED_APPS`. Per `CORE_ARCHITECTURE_PLAN.md` § 1.

### 2.2 — Conventions test ⬜
Every plugin has `plugin.toml`, an **explicit** `app_label`, and the four prefixes (table,
permission, route, frontend). Plus the cross-plugin import ban, by AST scan.

### 2.3 — `scripts/plugins.py` ⬜
`new` (scaffold from a template), `link` (symlink the frontend half), `list`.

### 2.4 — An example plugin ⬜
One trivial plugin in its own repo, as a submodule, proving the whole path: model → migration →
permission → route → nav entry → frontend page. **This is the acceptance test for Phase 2** — if
building it is awkward, the seam is wrong, and that is much cheaper to learn here than at plugin
four.

### 2.5 — Frontend plugin mounting ⬜
`src/plugins/registry.generated.ts` + the `(plugins)/[plugin]/[[...slug]]` catch-all.

---

## Phase 3 — reusability

### 3.1 — `scripts/setup.sh` ⬜
Rename from the directory name, generate a **fresh `SECRET_KEY`**, write env files, migrate, seed,
print the URL. Idempotent and safe to re-run.

### 3.2 — `core.manifest.json` + `scripts/core_doctor.py` ⬜
A SHA per core file; the doctor names every core file a checkout has changed. Regenerated **only in
this repo** — doing it in a product records that product's drift as correct.

### 3.3 — `core-guard.yml` ⬜
Fail a PR that edits `core/` without a `core-change` label. In the core repo itself, instead assert
the manifest was regenerated.

### 3.4 — Docker Compose ⬜
Postgres + Redis + both apps. Closes **DB-12** properly by making Postgres the default local
database.

---

## Phase 4 — the real test

### 4.1 — Build a second product on it ⬜
**Nothing proves a core is reusable until something else is built on it.** Whatever hurts the second
time is the design flaw. It is far cheaper to find at product two than at product five.

---

## Not in any phase — do these when they come up

- **DB-7** — refuse `DEBUG=True` and placeholder secrets when not in development
- **DB-8** — production security settings (`SECURE_SSL_REDIRECT`, secure cookies, HSTS)
- **DB-9** — `LOGGING` configuration with request correlation
- **DB-11** — a readiness probe that actually checks the database
- **DB-4** — generate frontend types from `/api/schema/`
- **DB-3** — `mypy` + `django-stubs`
- **DB-13** — a `seed` management command
