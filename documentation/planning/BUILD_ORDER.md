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

## The order, and why it is this one

**Decided 2026-09-21 by the repository owner: authentication first, then authorization, then RBAC.**
The platform comes before the tooling. Phases 0 and 1 are that decision; the enforcement work that
used to lead — test stack, architecture tests, CI — is now Phase 2.

⚠️ **What the trade costs, recorded so it is a known cost rather than a surprise.** Several Phase 1
acceptance criteria end in *"and has tests"* or name `test_route_enforcement.py`. Until **2.1**
installs `pytest`, none of those sentences can be satisfied; until **2.3** adds CI, nothing
re-checks them when a later change breaks them. Two legitimate ways to hold it:

- **Pull 2.1 forward on its own.** It is a dependency-and-config task, not a feature, and it turns
  *"has tests"* from an aspiration into a gate for everything in Phase 1. **Recommended.**
- **Take the debt deliberately.** Build Phase 1, then land 2.1–2.3 immediately after. Safe only if
  that *immediately* is real. Already tracked as `TECH_DEBT` **DB-5** / **DB-6**.

---

## Phase 0 — settle before the first migration

*Neither of these is a day's work, and neither is implementation. Both are settled by accident the
moment someone writes the first migration or the first authenticated endpoint — which is exactly
what Phase 1 does. That is why they sit in front of it rather than inside it.*

### 0.1 — 🚧 DECISION: custom `User` model or Django's ⬜
**This is first for a reason.** `AUTH_USER_MODEL` must be settled **before any migration references
it**. Swapping later is one of Django's genuinely painful migrations.

Answer even if the answer is "the default is fine" — an unrecorded default is not a decision.
Recommendation: **add a custom user model now** (`core.User` subclassing `AbstractUser`), because it
costs nothing today and is very expensive to add at product three. Closes **DB-10**.

**Done when:** an ADR exists, and if a custom model was chosen, `AUTH_USER_MODEL` is set and migrated
before anything else.

### 0.2 — 🚧 DECISION: the auth model ⬜
Read [`AUTH_RND.md`](AUTH_RND.md), answer its four questions, pick session / JWT / JWT-in-cookies,
write the ADR. Closes **DB-1**.

**Done when:** the ADR is Accepted and `ROADMAP.md` no longer contradicts `config/settings.py`.

---

## Phase 1 — authentication, authorization, RBAC

> 📘 **The build spec for this whole phase is [`../system-design/AUTH_BLUEPRINT.md`](../system-design/AUTH_BLUEPRINT.md)** — every table,
> file and flow, with each task below mapped to its chapters in that document's § 15.

*The platform. **1.1 → 1.2 → 1.4 is the owner's stated order**: who you are, then what you may do,
then how that is granted. 1.3 sits between them because RBAC's catalog is assembled from registry
registrations and cannot be built without the seam.*

### 1.0 — Dependencies and the deployment contract ⬜
*Added 2026-09-21 by the design review. **Nothing else in Phase 1 builds without it** — the spec as
written imports five libraries the project does not have.*

Per [`AUTH_BLUEPRINT.md`](../system-design/AUTH_BLUEPRINT.md) Ch. 16 and 17: add `pyjwt`, `pyotp`,
`cryptography`, `argon2-cffi` and `redis` to `backend/pyproject.toml`; add `CACHES` (from
`CACHE_URL`), `TRUSTED_PROXY_COUNT`, `ADMIN_ENABLED`, the `EMAIL_*` keys and `PASSWORD_HASHERS`;
write `core/http.py::client_ip()`; tighten the CORS settings. Every new key goes into `.env.example`
with a placeholder in the same change.

⚠️ `backend/pyproject.toml` and `backend/config/settings.py` are **protected files** — ask first.

**Done when:** `manage.py check` passes with `CACHE_URL` pointing at Redis, `client_ip()` returns
`REMOTE_ADDR` when `TRUSTED_PROXY_COUNT=0` and ignores a spoofed `X-Forwarded-For`, and
`.env.example` documents every new key.

### 1.1 — Authentication ⬜
Implement what 0.2 decided: register, login, logout, `/me`, password reset, and the frontend half in
`src/lib/api.ts`.

⚠️ **If the decision was any cookie-based scheme:** an `httpOnly` cookie **cannot be forwarded from a
Next.js server component**, so authenticated data must be fetched client-side and public data
server-side. Getting these backwards **fails silently**. Write the rule into `NEXTJS_STANDARDS.md`
in this same PR.

**Done when:** a login round-trip is tested (anonymous 401 → sign in → recognised → sign out → 401),
and a wrong password and an unknown address answer **identically** (no user enumeration). Once
**2.2** exists, `test_route_enforcement.py` must also still pass.

### 1.2 — Authorization — the two enforcement layers ⬜
The mechanism that answers *may this request do this*, per
[`../system-design/RBAC_DESIGN.md`](../system-design/RBAC_DESIGN.md) §§ "The two layers of checking"
and "Fail closed, everywhere":

- `Permission` and `PermissionGroup` models, plus the **code-declared** catalog and an idempotent
  seeder. Permissions are declared in code and seeded to the database, never edited in it
- **Layer 1 — entity:** a `HasPermission("<module>.<feature>.<action>")` DRF permission class
- **Layer 2 — object:** `visible_to(user)` on the first model's queryset, per `DATA_MODEL.md` § 5
- `is_superuser` bypasses every check, exactly as Django does it. Do not invent a second concept

⚠️ **Layer 1 alone is the classic RBAC bug.** `users.users.update` says a user may edit *users*; it
does not say they may edit *this* user. A route that checks only Layer 1 and then looks up by id
from the URL lets any permitted user edit any row.

**Done when:** an endpoint gated on a permission nobody holds refuses everyone; `visible_to()` with
no rule for a user returns `.none()` and never `.all()`; and a permission code absent from the
catalog is denied **and logged as a bug**, because that means a typo or a missing seed.

### 1.3 — The registry seam ⬜
*Prerequisite for 1.4 — the RBAC catalog is assembled from registrations, so the seam has to exist
before there is anything to assemble.*

`backend/core/registry.py` per [`CORE_ARCHITECTURE_PLAN.md`](CORE_ARCHITECTURE_PLAN.md) § 2 —
permissions, navigation, api_routes, events, jobs, search, settings, health. Registration is
boot-time, one-way, read-only afterwards. **`registry.py` imports nothing from `core`.**

**Done when:** a throwaway app registering a permission group and a nav section appears in both
without any core file naming it.

### 1.4 — RBAC ⬜
Roles on top of 1.2's permissions, **through the registry**, not a hard-coded catalog. Permission
names are `<module>.<feature>.<action>`. Fail closed, matching DRF's existing `IsAuthenticated`
default.

- `Role` and `UserRole` — roles hold permissions, users hold roles
- Seeded system roles `administrator` (every permission, recomputed on every seed) and `staff`
  (**nothing** — the safe default for a new account), both `is_system=True` and seeded idempotently.
  ⚠️ The grant recomputation runs in `post_migrate` **after** the catalog seed, not in the role
  migration — at migration time there are no permissions to grant (`AUTH_BLUEPRINT.md` Ch. 13)
- `/me` returns the current user's permission codes; the frontend `can()` helper uses them **only to
  hide UI**, never as the authorization decision
- The roles admin screen **last** — it is the easiest part and the one most likely to be built first

**Done when:** a user with a role holding no permissions is refused by every gated endpoint, and the
catalog is assembled from registrations rather than a literal.

### 1.5 — Users CRUD ⬜
The reference module every later module copies. Backend viewset + serializers + services; frontend
list, detail, create, edit. Follow `DJANGO_STANDARDS.md` § 3 layering exactly — this one is the
template, so shortcuts here get copied forever.

**Done when:** full CRUD works end to end, is permission-gated, is paginated, and has tests.

### 1.5b — Email and the first account ⬜
*Added 2026-09-21. `AUTH_BLUEPRINT.md` Ch. 18 and § 19.1 — **1.1c and 1.1d cannot be demonstrated
without this**, because password reset and invitations both send mail, and with `is_active`
defaulting to `False` nothing can create account one.*

Email templates (`.txt` **and** `.html`) plus `send_password_reset()` / `send_invitation()`, sent
from `transaction.on_commit()` and never inside the transaction; links built from
`FRONTEND_BASE_URL`, **never** from the `Host` header. Plus `manage.py bootstrap_admin`.

**Done when:** a reset email appears on the console in dev and its link works; `bootstrap_admin`
run twice creates one account and exits non-zero the second time.

### 1.6 — `core/` vs `project/` split ⬜
Split the backend into `core/` (platform) and `project/` (product) with `config/` as composition
root; mirror on the frontend. Add the boundary tests: `core/` must not import `project`, and
`frontend/src/core/` must not import `src/project/`.

**Done when:** deleting `project/` leaves a working platform, and a test asserts it.

---

### 1.7 — Operations and the admin decision ⬜
*Added 2026-09-21. `AUTH_BLUEPRINT.md` § 19.2–19.3 and Ch. 20.*

`manage.py auth_cleanup` (retention for sessions, login attempts and reset tokens —
**never** the activity log); `MAX_SESSIONS_PER_USER`; `JWT_SIGNING_KEY_FALLBACKS` with a `kid`
header, so rotating the signing key is not a scheduled outage; and `/admin/` mounted only when
`ADMIN_ENABLED`, with the `rbac` models **not registered** — the admin otherwise bypasses every
guard in `AUTH_BLUEPRINT.md` Ch. 8 and writes no audit row.

**Done when:** `auth_cleanup --dry-run` reports counts and deletes nothing; a token signed with a
fallback key still verifies; `/admin/` is absent with `ADMIN_ENABLED=False`.

---

## Phase 2 — make the rules enforceable

*Nothing in this repository can currently fail a build. Until that changes, every convention is
advisory — including every rule Phase 1 just wrote down. **2.1 is the one task worth pulling forward
into Phase 1**; see "The order, and why it is this one" above.*

### 2.1 — Install the test stack ⬜
Add `pytest`, `pytest-django`, `factory_boy`, `pytest-cov` to the `dev` dependency group in
`backend/pyproject.toml`. Add `pytest.ini_options` to `pyproject.toml` with `DJANGO_SETTINGS_MODULE`.
Add `"typecheck": "tsc --noEmit"` to `frontend/package.json` (closes `TECH_DEBT` **DB-2**).

**Done when:** `cd backend && uv run pytest` runs and reports at least one passing smoke test that
hits `/api/health/`. `cd frontend && npm run typecheck` passes.

### 2.2 — The architecture tests ⬜
In `backend/tests/architecture/`, per [`TESTING_STRATEGY.md`](TESTING_STRATEGY.md) § "The four tests":

- `test_route_enforcement.py` — walk Django's URL resolver for **every** route, call each
  unauthenticated, fail on anything that is not 401/403. **A 404 counts as a failure** — it means the
  handler ran a lookup before checking who was asking
- `test_migrations.py` — one migration head per app, and every model has a table

**Done when:** both pass, and deliberately breaking one (open a view with `AllowAny`, branch a
migration) makes the right test fail with a readable message.

### 2.3 — CI ⬜
`.github/workflows/ci.yml`, **two jobs** so a Python failure still reports the TypeScript result:
backend (`ruff check` · `ruff format --check` · `manage.py check` · `makemigrations --check
--dry-run` · `pytest`) and frontend (`npm ci` · `lint` · `typecheck` · `next build`).

Run the backend job against a **PostgreSQL 16 service**, not SQLite — a suite proving behaviour
against a database nobody deploys proves it in the wrong place.

**No `continue-on-error` on any step.** A non-blocking check is a check nobody reads.
Closes **DB-5** / **DB-6**.

**Done when:** a PR with a deliberate lint error goes red, and a clean PR goes green.

---

## Phase 3 — the plugin system

### 3.1 — Plugin discovery ⬜
`backend/core/plugins.py` — scan `backend/plugins/*/plugin.toml`, add to `sys.path`, append to
`INSTALLED_APPS`. Per `CORE_ARCHITECTURE_PLAN.md` § 1.

### 3.2 — Conventions test ⬜
Every plugin has `plugin.toml`, an **explicit** `app_label`, and the four prefixes (table,
permission, route, frontend). Plus the cross-plugin import ban, by AST scan.

### 3.3 — `scripts/plugins.py` ⬜
`new` (scaffold from a template), `link` (symlink the frontend half), `list`.

### 3.4 — An example plugin ⬜
One trivial plugin in its own repo, as a submodule, proving the whole path: model → migration →
permission → route → nav entry → frontend page. **This is the acceptance test for Phase 3** — if
building it is awkward, the seam is wrong, and that is much cheaper to learn here than at plugin
four.

### 3.5 — Frontend plugin mounting ⬜
`src/plugins/registry.generated.ts` + the `(plugins)/[plugin]/[[...slug]]` catch-all.

---

## Phase 4 — reusability

### 4.1 — `scripts/setup.sh` ⬜
Rename from the directory name, generate a **fresh `SECRET_KEY`**, write env files, migrate, seed,
print the URL. Idempotent and safe to re-run.

### 4.2 — `core.manifest.json` + `scripts/core_doctor.py` ⬜
A SHA per core file; the doctor names every core file a checkout has changed. Regenerated **only in
this repo** — doing it in a product records that product's drift as correct.

### 4.3 — `core-guard.yml` ⬜
Fail a PR that edits `core/` without a `core-change` label. In the core repo itself, instead assert
the manifest was regenerated.

### 4.4 — Docker Compose ⬜
Postgres + Redis + both apps. Closes **DB-12** properly by making Postgres the default local
database.

⚠️ **Redis itself is no longer a Phase 4 concern** — task `1.0` needs it. `AUTH_BLUEPRINT.md` § 17.4
shows the permission cache, session liveness and every throttle are all per-worker on Django's
default `LocMemCache`, which makes a shared cache a correctness requirement rather than a
performance one. This task packages it; it does not introduce it.

---

## Phase 5 — the real test

### 5.1 — Build a second product on it ⬜
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
