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

### 0.1 — 🚧 DECISION: custom `User` model or Django's ✅
**Decided 2026-10-11 — [ADR-0008](../adr/0008-custom-user-model-email-identity.md):** a custom
`users.User` (`AbstractBaseUser + PermissionsMixin`) per `AUTH_BLUEPRINT.md` A1–A3, with email as
the login, no username and boolean states. It is not `core.User(AbstractUser)` as recommended below,
because the blueprint keeps identity out of `core`. `AUTH_USER_MODEL = "users.User"` is set, and
`users/0001_initial` (`User` only, § 3.1 columns, admin read-mostly) is the project's first
migration. That also delivers the model half of **1.1a**.

**This is first for a reason.** `AUTH_USER_MODEL` must be settled **before any migration references
it**. Swapping later is one of Django's genuinely painful migrations.

Answer even if the answer is "the default is fine" — an unrecorded default is not a decision.
Recommendation: **add a custom user model now** (`core.User` subclassing `AbstractUser`), because it
costs nothing today and is very expensive to add at product three. Closes **DB-10**.

**Done when:** an ADR exists, and if a custom model was chosen, `AUTH_USER_MODEL` is set and migrated
before anything else.

### 0.2 — 🚧 DECISION: the auth model ✅
**Decided 2026-10-11 — [ADR-0009](../adr/0009-jwt-in-httponly-cookies.md):** option C. A JWT access
and refresh pair in `httpOnly` cookies, rotation with reuse detection, and a `users_user_session` row
per refresh token, exactly as `AUTH_BLUEPRINT.md` A4–A5 and Ch. 6 specify. Machine callers use the
`API_PLATFORM.md` tokens instead. The owner runs several servers from day one, so the shared cache
in **1.0** is required, not optional.
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

### 1.0 — Dependencies and the deployment contract ✅
**Done 2026-10-11.** The five libraries are in `pyproject.toml`. `settings.py` has `CACHES` from
`CACHE_URL`, `TRUSTED_PROXY_COUNT`, `ADMIN_ENABLED` (now gating `/admin/` in `config/urls.py`), the
email keys, `FRONTEND_BASE_URL`, Argon2-first `PASSWORD_HASHERS`, and `x-csrf-token` in
`CORS_ALLOW_HEADERS`. `core/http.py::client_ip()` has 7 tests in `core/tests.py`. Docker runs Redis
as the cache. Not here: the `dbx.E005` boot check (it lands with the Ch. 9.2 checks in 1.2a), and
the JWT/cookie keys of § 12 (1.1b).
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

### 1.1 — Authentication ✅
*Complete 2026-10-11 with invitations (§ 10.2a).*
*Partly done 2026-10-11, **1.1b** in the blueprint's split (`AUTH_BLUEPRINT.md` § 15):*
- `UserSession` and `LoginAttempt` (`users/0002`);
- `users/tokens.py` (issue, rotate with reuse detection and the A23 grace window, revoke);
- `CookieJWTAuthentication` with the session-bound CSRF check;
- login, refresh, logout, sign-out-everywhere-else and `/me`, with `Cache-Control: no-store`;
- the frontend half in `src/core/lib/api.ts` + `src/core/lib/auth.ts`, a minimal `/login` page, and the
  client-side rule in `NEXTJS_STANDARDS.md` § 3.

Both acceptance criteria below pass (`users/tests/test_auth_flow.py`), and so does
`test_route_enforcement.py`.

*Also done 2026-10-11, **1.1c**:*
- `PasswordResetToken` (`users/0003`), with `forgot/` (always 204) and `reset/` (single-use, kills
  every other link);
- the password-change cascade on any change (`users/signals.py`);
- `LoginThrottle` (5/min per address+IP) and `PasswordResetThrottle` (3/hour per address);
- progressive lockout (`users/services/lockout.py`);
- forgot/reset pages at `/forgot-password` and `/reset-password`.

`AUTH_BLUEPRINT.md` § 6.7a records the decisions.

*Also done 2026-10-11, **1.1d** (most of it):*
- `MfaDevice` and `MfaRecoveryCode` (`users/0004`);
- TOTP setup, confirm, verify and disable, with an encrypted secret, the ±1-step replay guard and
  10 single-use recovery codes;
- the login code step (`mfa_token`), and the enrolment gate for `mfa_enforced` users;
- `RequiresRecentAuth` (423, off until opted in) and `password/confirm/`;
- frontend: the login code step and `/account/security`.

§ 6.9a records the decisions. **Still to do for 1.1: invitations**, which need `rbac.Role`. Do
them straight after 1.2 introduces roles. There is no self-registration:
accounts arrive by invitation (A25).
Implement what 0.2 decided: register, login, logout, `/me`, password reset, and the frontend half in
`src/core/lib/api.ts`.

⚠️ **If the decision was any cookie-based scheme:** an `httpOnly` cookie **cannot be forwarded from a
Next.js server component**, so authenticated data must be fetched client-side and public data
server-side. Getting these backwards **fails silently**. Write the rule into `NEXTJS_STANDARDS.md`
in this same PR.

**Done when:** a login round-trip is tested (anonymous 401 → sign in → recognised → sign out → 401),
and a wrong password and an unknown address answer **identically** (no user enumeration). Once
**2.2** exists, `test_route_enforcement.py` must also still pass.

### 1.2 — Authorization — the two enforcement layers ✅
**Done 2026-10-11** (blueprint 1.2a–c):
- the code catalog through `core.registry`, seeded by `rbac.seeding` (`post_migrate` and
  `seed_permissions`);
- the five `rbac` tables;
- `RBACBackend` with versioned caching and the audited superuser bypass;
- Layer 1, `core.permissions.has_permission(...)`;
- Layer 2, `core.querysets.VisibleToQuerySet` and `User.objects.visible_to()`;
- `dbx.E005` / `E006`;
- the code↔catalog architecture test.

`AUTH_BLUEPRINT.md` § 7.6a records the decisions. Done-when: a permission nobody holds refuses
everyone (`test_has_permission_refuses…`); `visible_to()` with no rule is `.none()`; an unknown code
cannot be granted (`set_grants` raises), and one referenced in code fails the catalog test.
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

### 1.3 — The registry seam ✅
**Done 2026-10-11** (junior session): `core/registry.py` holds permissions, navigation (with a
permission cross-check at seal), health and api_routes. It is stdlib-only, all-or-nothing, and seals
on first read. The done-when test registers a throwaway `AppConfig` into a fresh registry and finds
it in every catalog with no core file naming it. `events`, `jobs`, `search` and `settings` arrive
with their phases (`CORE_ARCHITECTURE_PLAN.md` § 2 note).
*Prerequisite for 1.4 — the RBAC catalog is assembled from registrations, so the seam has to exist
before there is anything to assemble.*

`backend/core/registry.py` per [`CORE_ARCHITECTURE_PLAN.md`](CORE_ARCHITECTURE_PLAN.md) § 2 —
permissions, navigation, api_routes, events, jobs, search, settings, health. Registration is
boot-time, one-way, read-only afterwards. **`registry.py` imports nothing from `core`.**

**Done when:** a throwaway app registering a permission group and a nav section appears in both
without any core file naming it.

### 1.4 — RBAC ✅
**Done 2026-10-11:**
- the declarative gate (`BaseAPIView` / `BaseViewSet`, `DefaultDeny`, `dbx.E001`/`E004`/`E007`),
  with every endpoint moved onto it;
- the system roles `administrator` and `staff` (`rbac/0002`, recomputed after the catalog seed);
- the § 8.4 services with the system-role, elevated-role, last-administrator and role-in-use
  guards;
- `/api/rbac/` per § 10.3;
- frontend: `can()` / `usePermissions()` and the roles screen at `/settings/roles`.

`AUTH_BLUEPRINT.md` § 8.6 records the decisions. Done-when: a role holding no permissions is
refused by a gated endpoint (`test_a_role_holding_no_permissions_is_refused`), and the catalog is
assembled from `ready()` registrations.
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

### 1.5 — Users CRUD ✅
**Done 2026-10-11:**
- `/api/users/` (list with search, create with a set-password email, retrieve, update,
  deactivate/activate, revoke sessions) and invitations (send, list, revoke, public accept) on
  `BaseViewSet`;
- `users/services/{users,invitations}.py` and `users/0005_invitation`;
- frontend `/users`, `/users/new`, `/users/[publicId]` (with role assignment), `/users/invitations`
  and `/accept-invitation`.

`AUTH_BLUEPRINT.md` § 10.2a records the decisions.
The reference module every later module copies. Backend viewset + serializers + services; frontend
list, detail, create, edit. Follow `DJANGO_STANDARDS.md` § 3 layering exactly — this one is the
template, so shortcuts here get copied forever.

**Done when:** full CRUD works end to end, is permission-gated, is paginated, and has tests.

### 1.5b — Email and the first account ✅
**Done 2026-10-11:** the reset, setup and invitation emails (`.txt` + `.html`, sent on commit, links
from `FRONTEND_BASE_URL`), plus `manage.py bootstrap_admin` (in `rbac/`, built by the junior).
*Added 2026-09-21. `AUTH_BLUEPRINT.md` Ch. 18 and § 19.1 — **1.1c and 1.1d cannot be demonstrated
without this**, because password reset and invitations both send mail, and with `is_active`
defaulting to `False` nothing can create account one.*

Email templates (`.txt` **and** `.html`) plus `send_password_reset()` / `send_invitation()`, sent
from `transaction.on_commit()` and never inside the transaction; links built from
`FRONTEND_BASE_URL`, **never** from the `Host` header. Plus `manage.py bootstrap_admin`.

**Done when:** a reset email appears on the console in dev and its link works; `bootstrap_admin`
run twice creates one account and exits non-zero the second time.

### 1.6 — `core/` vs `project/` split ✅
**Done 2026-10-11, [ADR-0010](../adr/0010-platform-layer-is-logical.md)** (the owner chose a
*logical* layer):
- `core`, `users` and `rbac` are the platform; `backend/project/` (with `wiring.py`) is product
  code, loaded only when present;
- `config/urls.py` mounts `registry.api_routes`;
- `tests/architecture/test_core_boundary.py` (AST) and `test_platform_without_project.py` (copies
  the backend without `project/` and boots it, with a positive control);
- frontend `src/core/` plus `src/app/(core)/` and `src/project/`, with an ESLint boundary rule.
Split the backend into `core/` (platform) and `project/` (product) with `config/` as composition
root; mirror on the frontend. Add the boundary tests: `core/` must not import `project`, and
`frontend/src/core/` must not import `src/project/`.

**Done when:** deleting `project/` leaves a working platform, and a test asserts it.

---

### 1.7 — Operations and the admin decision ✅
**Done 2026-10-11:**
- `manage.py auth_cleanup [--dry-run]`;
- `MAX_SESSIONS_PER_USER`;
- `JWT_SIGNING_KEY_FALLBACKS` with a `kid` header;
- the admin is behind `ADMIN_ENABLED` (since 1.0), `rbac` is unregistered (since 1.2), and the
  user admin is read-mostly with `is_staff` and `is_superuser` read-only (since 0.1).

`AUTH_BLUEPRINT.md` § 19.3a records the details. **Phase 1 is complete.**
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

### 2.1 — Install the test stack ✅
**Done 2026-10-11, pulled forward ahead of 1.1 as recommended above.** `uv run pytest` runs 34
tests on `config.settings_test`. That settings module pins every env value and puts the cache, email
and storage in memory. A root `conftest.py` runs the `OPERATIONS.md` § 11 test-database guard before
any database is created and clears the cache per test. There are factories in `tests/factories.py`,
meta-tests for the guard, isolation and factories, and a `/api/health/` smoke test.
`npm run typecheck` exists. **Not yet:** `time-machine`, the outbound-HTTP block, xdist, and
coverage floors (`TESTING_STRATEGY.md` step 4).
Add `pytest`, `pytest-django`, `factory_boy`, `pytest-cov` to the `dev` dependency group in
`backend/pyproject.toml`. Add `pytest.ini_options` to `pyproject.toml` with `DJANGO_SETTINGS_MODULE`.
Add `"typecheck": "tsc --noEmit"` to `frontend/package.json` (closes `TECH_DEBT` **DB-2**).

**Done when:** `cd backend && uv run pytest` runs and reports at least one passing smoke test that
hits `/api/health/`. `cd frontend && npm run typecheck` passes.

### 2.2 — The architecture tests ✅
**Done 2026-10-11.** `tests/architecture/`:
- `test_route_enforcement.py` walks every `/api/` route and calls each with five methods,
  anonymously. A meta-test proves the checker flags an `AllowAny` view and a lookup-first 404 while
  passing a gated view.
- `test_public_routes.py` pins the new `core/routes.py` `PUBLIC_ROUTES` ledger: health, schema and
  docs, each with a reason.
- `test_migrations.py` checks one head per app, no missing migration, and a table for every model.

Both deliberate breaks fail with a readable message. Removing `core:health` from the ledger reports
`GET /api/health/ [core:health] -> 200`. Two `0002` migrations report
`users: 0002_probe_branch_a, 0002_probe_branch_b`.
In `backend/tests/architecture/`, per [`TESTING_STRATEGY.md`](TESTING_STRATEGY.md) § "The four tests":

- `test_route_enforcement.py` — walk Django's URL resolver for **every** route, call each
  unauthenticated, fail on anything that is not 401/403. **A 404 counts as a failure** — it means the
  handler ran a lookup before checking who was asking
- `test_migrations.py` — one migration head per app, and every model has a table

**Done when:** both pass, and deliberately breaking one (open a view with `AllowAny`, branch a
migration) makes the right test fail with a readable message.

### 2.3 — CI ⬜
*In place since 2026-10-11:* `.github/workflows/ci.yml` as specified below. The suite was run
locally against PostgreSQL 16 first (43 passed), and the frontend `next build` passed. **Still
open:** the "Done when" proof below, a deliberately red PR next to a green one.
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

### 3.1 — Plugin discovery ✅
`backend/core/plugins.py` — scan `backend/plugins/*/plugin.toml`, add to `sys.path`, append to
`INSTALLED_APPS`. Per `CORE_ARCHITECTURE_PLAN.md` § 1.

*Done 2026-10-11.* `config/settings.py` runs `INSTALLED_APPS += installed_apps(BASE_DIR / "plugins")`.
Manifests are validated before any plugin code runs (the minimal schema is in `EXTENSIBILITY.md`
§ 17), and absent vs broken follows DB-18. The public-route ledger became `registry.public_routes`
(DB-22) in the same change, so a plugin can declare its anonymous routes. Tests:
`tests/test_plugins.py`, `tests/test_registry.py`.

### 3.2 — Conventions test ✅
Every plugin has `plugin.toml`, an **explicit** `app_label`, and the four prefixes (table,
permission, route, frontend). Plus the cross-plugin import ban, by AST scan.

*Done 2026-10-11.* `tests/architecture/test_plugin_conventions.py` applies the rules in
`plugin_rules.py` to every installed plugin:
- **Boundary:** no import of another plugin or `project`, including `import_module("…")`.
- **Label:** set on the class and equal to the manifest's.
- **Tables:** explicit `db_table` with the prefix, M2M tables included.
- **Registrations in their lane:** permission module, `/api/<route>/` with `app_name = <label>`,
  nav paths under `/<frontend>/`, public routes `<label>:`.
- **Registry keys derive from the plugin:** group code `<label>[_…]`, nav section and health keys
  `<frontend>[-…]`. Otherwise a plugin could take a key core registers later.
- **No shadowing:** no frontend prefix that a static page already serves.

The platform may not import any `djx_*` package (`test_core_boundary.py`), and `dbx.E009` makes a
catalog that cannot seal fail `manage.py check` instead of a request.

Registrations are attributed by the module that called `register()`: every catalog now records it
(`owner()`), so a plugin registering under another module's name is caught. Meta-tests run the
rules against the rendered scaffold (passes) and broken copies (each rule fails). With no plugin
installed, the per-plugin tests skip, saying "no plugin installed". CI installs the example plugin,
so there they run.

### 3.3 — `scripts/plugins.py` ✅
`new` (scaffold from a template), `link` (symlink the frontend half), `list`.

*Done 2026-10-11* (junior session; the registry command was added by the lead).
- `new` renders `scripts/plugin_template/` (all `*.tmpl`) transactionally. It validates the name
  (≤ 30 characters; not reserved) and refuses to leave a plugin that breaks discovery.
- `link` makes a relative symlink and regenerates `frontend/src/plugins/registry.generated.ts`.
- `registry` regenerates that file alone; `list` shows each plugin's link status.
- Tests: `tests/test_plugins_script.py`, including one that the registry in the tree matches the
  links in the tree.

### 3.4 — An example plugin ✅
One trivial plugin in its own repo, as a submodule, proving the whole path: model → migration →
permission → route → nav entry → frontend page. **This is the acceptance test for Phase 3** — if
building it is awkward, the seam is wrong, and that is much cheaper to learn here than at plugin
four.

*Done 2026-10-11, with one owner-approved change of location.* It lives in
`examples/plugins/notes/`, **not** in its own repository as a submodule: as a submodule of this
boilerplate it would ship a demo plugin into every product copied from it.
- **What it is:** generated by `plugins.py new notes`, then grown into a model scoped by
  `visible_to()`, a service, a viewset, three permissions, a nav section and a `/notes` page.
- **How it is proved:** CI copies and links it, then runs the checks, the suite, lint, typecheck
  and `next build` with it installed. A headless-Chrome run on the Docker stack covered sign-in →
  nav → `/notes` → create → delete.
- **Was it awkward?** Two seams were missing, and both now exist: a navigation endpoint
  (`GET /api/me/navigation/`, the first slice of 8.2) and the lint glob for symlinked plugin files.

### 3.5 — Frontend plugin mounting ✅
`src/plugins/registry.generated.ts` + the `(plugins)/[plugin]/[[...slug]]` catch-all.

*Done 2026-10-11.* A plugin's `frontend/index.ts` default-exports `{ name, pages }`, and
`src/core/lib/plugin-pages.ts::resolvePluginPage()` maps `/<prefix>/<…slug>` to a lazily loaded page.
Anything unclaimed is a 404, and static core routes always win.
- **DB-28:** `turbopack.root` is the repository (`next.config.ts`). The Docker frontend mounts the
  checkout under `/repo` so the same relative symlinks resolve there.
- **Lint:** `eslint .` does not descend into symlinked directories, so `npm run lint` is
  `eslint . src/plugins/*`. `tsc` already follows them.
- **Boundary (ESLint):** core never imports `@/plugins`. A plugin imports `@/core/…` and its own
  files only: one rule block per directory depth refuses a `../` that climbs out of the plugin's
  root.
- **Shadowing:** `plugins.py new` / `link` / `registry` refuse a prefix the frontend already serves
  statically (`page_segments()`).

---

## Phase 4 — reusability

### 4.1 — `scripts/setup.sh` ✅
Rename from the directory name, generate a **fresh `SECRET_KEY`**, write env files, migrate, seed,
print the URL. Idempotent and safe to re-run.

*Done 2026-10-22* (junior `djangobasex-f6`, reviewed by the lead).
- **What it does:** one command from a fresh clone to a signed-in app, on Docker (Postgres + Redis)
  or with `--no-docker` (SQLite, host dev servers).
- **Identity per checkout:** the slug comes from the directory (`scripts/lib/project.sh`), which
  names the compose project `<slug>-dev` and gives each checkout its own cookie prefix.
- **Env files and secrets:** writes `.env`, `backend/.env` and `frontend/.env.local` (mode 600).
  Only empty or placeholder keys are filled, with secrets from `core/secret_policy.py`. The boot
  audit and `manage.py generate_secret` use the same module.
- **Ports:** free loopback ports are chosen once and kept.
- **Bring-up:** builds the images, migrates, runs `bootstrap_admin` only when no user exists, and
  waits until both apps answer.
- **Proof:** a re-run leaves all three env files byte-for-byte identical, a second checkout runs
  beside the first, and a taken port is re-chosen. `--reset` asks for the name to be typed back.
- **Tests:** `tests/infra/test_setup_script.py` and `tests/test_secret_policy.py`.

### 4.2 — `core.manifest.json` + `scripts/core_doctor.py` ✅
A SHA per core file; the doctor names every core file a checkout has changed. Regenerated **only in
this repo** — doing it in a product records that product's drift as correct.

*Done 2026-10-22.* Built to `ENGINEERING_PRACTICES.md` § 52.
- **Core is a list:** the trees and files in the manifest header (ADR-0010).
- **Drift classes:** modified, missing, and added. An untracked file under a core tree counts as
  added.
- **Modes:** `--json`, `--verify` (is the manifest current?) and `--list-core`.
- **`--write` is guarded:** it refuses unless `origin` is this repository, and never echoes the URL.
- **Tests:** `tests/infra/test_core_doctor.py`, including that the committed header equals the core
  list. Usage is in `UPGRADING.md` § "If you edited core".

### 4.3 — `core-guard.yml` ✅ (local proof; GitHub run pending)
Fail a PR that edits `core/` without a `core-change` label. In the core repo itself, instead assert
the manifest was regenerated.

*Done 2026-10-22.*
- **How it decides:** this repository is recognised by its explicit name (case-insensitive).
  Every other repository is a product.
- **Core:** a PR that touches core without the manifest fails, and `--verify` runs on PRs and on
  pushes to `main`.
- **Product:** a PR that touches core needs the `core-change` label. The doctor also runs on the
  whole tree, so drift from a direct push or a merge fails as well. A missing manifest is never
  excused by the label.
- **Proof:** `actionlint` is clean. The workflow's own `run:` steps were executed under bash 5 in
  throwaway repositories: **15/15 scenarios** behaved as specified (core: clean, unregenerated,
  regenerated, stale, name case, push; product: clean, unlabelled, labelled, deleted file, drifted
  main, no manifest, push clean/drifted).
- **Still to see:** a real GitHub run, which comes with the 2.3 proof PRs.

### 4.4 — Docker Compose ✅
*Done 2026-10-22* (junior `djangobasex-f6`, reviewed by the lead).
- **Services:** PostgreSQL 16 (OPERATIONS § 12 server settings, named volume), Redis 7.4 (password,
  not published) and both apps, namespaced by `COMPOSE_PROJECT_NAME`.
- **Hardening:** ports on 127.0.0.1 only, every secret `${VAR:?}`, `cap_drop: [ALL]`,
  `no-new-privileges`, capped log drivers, healthchecks, and uid 1000 in the app images. Nothing
  migrates on start.
- **Policy as tests:** `tests/infra/test_compose_policy.py` checks the file `docker compose config`
  resolves, and every rule has positive controls.
- **Proven on a running stack:** sign-in through the API, a second checkout side by side, and the
  `--reset` confirmation.
- **DB-12:** the default `setup.sh` path now develops against Postgres. A plain host `runserver`
  still uses SQLite by ADR-0005.

*Was partly in place since 2026-10-11:* `docker-compose.yml` runs **both apps for development** (live
reload, SQLite, ports on `127.0.0.1`) from `backend/Dockerfile.dev` and `frontend/Dockerfile.dev`.
What this task still adds: Postgres, Redis, the compose project naming of `OPERATIONS.md` § 1 and
the rest of the § 15 hygiene.

Postgres + Redis + both apps. Closes **DB-12** properly by making Postgres the default local
database.

⚠️ **Redis itself is no longer a Phase 4 concern** — task `1.0` needs it. `AUTH_BLUEPRINT.md` § 17.4
shows the permission cache, session liveness and every throttle are all per-worker on Django's
default `LocMemCache`, which makes a shared cache a correctness requirement rather than a
performance one. This task packages it; it does not introduce it.

---

## Phases 5–9 — the platform services

*Added 2026-09-29 from the platform study. The map of what each phase delivers, and why, is
[`PLATFORM_BLUEPRINT.md`](PLATFORM_BLUEPRINT.md); each task names the spec it builds to. Phases 5–9 are
**Tier 1 and Tier 2 core** — everything a product needs before it can be the "second product" of Phase 10.
Tier 3 modules (billing, approvals, help centre, …) are deliberately **not** in this order; they are built as
plugins when the first product that needs them arrives — [`../system-design/REUSABLE_MODULES.md`](../system-design/REUSABLE_MODULES.md).*

> ⚠️ **Resolve [`PLATFORM_BLUEPRINT.md`](PLATFORM_BLUEPRINT.md) § 5 before the tasks it touches.** Eleven places
> where an existing spec — or today's code — contradicts what the study learned are tracked in `TECH_DEBT`
> **DB-18 – DB-31**. Seven of them (DB-18, DB-19, DB-20, DB-25, DB-26, DB-30, DB-31) change Phase 0–3 tasks and are cheapest to fix *before* those tasks are built.

> **Pulling forward is allowed.** 5.1 and 6.1 are small and make every later task safer; take them as soon as
> Phase 2's test stack exists. Everything else stays in order.

---

## Phase 5 — configuration: nothing hard-coded

*Spec: [`../system-design/CONFIGURATION.md`](../system-design/CONFIGURATION.md).*

### 5.1 — Environment identity and the boot refusal ✅
**Done 2026-10-11 (pulled forward):**
- `core/env.py::is_production_like()` (the allow-list `development/local/test/ci`; everything
  else, including unset, `staging` and `Production`, is production-like);
- `core/config_audit.py` (`cfg.E002`–`E015`, `W001`–`W008`) runs as **the last line of
  `config/settings.py`** and refuses a production-like boot listing every problem, naming keys
  never values;
- `python -m core.config_audit` is the report-only pre-deploy step;
- `APP_ENV` is required (blank = production-like) and `.env.example` ships `development`;
  `AUTH_COOKIE_SECURE` defaults to production-like.

The done-when is met by `tests/test_production_boot.py`, which imports the real settings in a
subprocess without a `.env`. The CI step runs as part of pytest. Omitted rules are recorded in
`core/config_audit.py`.
One `is_production_like()` predicate (unknown `APP_ENV` counts as production), used by every check. The
production audit runs **at settings import** and raises `ImproperlyConfigured` listing every problem at once —
placeholder or short secrets, secrets equal to each other, `DEBUG`, console mail, localhost CORS, plain-text logs.
Keep `dbx.E005`–`E008` for `check --deploy`. Closes **DB-7**, **DB-19**.

**Done when:** importing settings with `APP_ENV=production` and the dev `.env` fails and names every problem; a
valid production config imports (tested *first*); a CI step asserts the refusal; `APP_ENV=Production` and
`APP_ENV=staging` are both treated as production-like.

### 5.2 — Project identity ✅
`PRODUCT_NAME`, `PRODUCT_SLUG`, `PRIMARY_DOMAIN` in settings; OTP issuer, default from-address, cookie names and the
API title derive from them. Shipped defaults announce themselves on screen.

*Done 2026-10-22* (lead: backend and frontend; junior `djangobasex-f6`: `setup.sh` and compose).
- **Shipped defaults:** `core/identity.py` holds them ("Unnamed product", `no-reply@localhost`) and
  the slug rule, which a test pins equal to `scripts/lib/project.sh`.
- **Derived from the three inputs:** `MFA_ISSUER`, `DEFAULT_FROM_EMAIL`, `AUTH_COOKIE_PREFIX`, the
  admin's `SESSION_COOKIE_NAME` and `CSRF_COOKIE_NAME`, the cache `KEY_PREFIX` and the OpenAPI title.
  An explicit env value still wins.
- **Production warning:** `cfg.W003` fires while the name or domain is still the shipped default.
- **Frontend:** `GET /api/public/config/` is a new public route, entered in the ledger. The root
  layout's `generateMetadata` (60 s ISR) titles every page `<page> — <product>`, and the sign-in
  and home pages show the name and tagline.
- **Scrubbing:** the scrubber covers the new admin cookie names.
- **`setup.sh`** writes `PRODUCT_SLUG` per checkout. Compose now requires `AUTH_COOKIE_PREFIX`,
  instead of defaulting it to the old literal.
- **Done-when:** `tests/architecture/test_no_boilerplate_identity.py` finds neither the name nor
  the old literal cookie prefix in core (with a positive control).
  `tests/test_identity.py::test_changing_the_name_changes_every_derived_value` imports the real
  settings in a fresh interpreter.

**Done when:** a test greps `backend/core/` and `frontend/src/core/` for the boilerplate's own name and finds
nothing outside the settings defaults; changing `PRODUCT_NAME` changes all four derived values.

### 5.3 — The typed settings registry ✅
*Done 2026-10-24* (junior `djangobasex-f6`, reviewed by the lead), backend only.
- **Declared in code:** `registry.settings.register(SettingDef(...))` or a frozen policy dataclass
  via `register_group`; validated at boot (`dbx.E009`).
- **Stored as overrides only:** `core_setting` holds `{"v": …}` rows with partial-unique scopes;
  core's first migration. `sync_settings` reports and never writes.
- **Read path:** cascade user → tenant → platform → code default, honouring declared scopes and
  locked rows; a shared-cache generation bumped per committed write; one snapshot per request;
  readers never raise on storage failure. Tenant is inert until `set_tenant_resolver()`.
- **Write path:** one writer (`set_value` / `reset`), audited old → new on commit, through the CLI
  (`set_setting`) and `GET/PATCH /api/core/settings/` behind `settings.settings.view|manage`.
- **Moved from env:** `security.reauth.actions` and `security.reauth.window_minutes`.
- **Proof:** 37 new tests, a defaults snapshot, an AST scan for unregistered or unread keys, and
  a plugin-conventions rule. 1105 passed on SQLite and on PostgreSQL 16.
`registry.settings.register(SettingDef(key, type, default, label, description, group, module, scopes, …))`, with
typed values (`Bool`, `Int(min, max)`, `Choice(…)`, … per `CONFIGURATION.md` § 9.1/§ 9.4);
`sync_settings` in `post_migrate` **validates and reports only — it has no write path, so it can never reset a
value** (§ 9.2: metadata lives in code, never in a table); strict coercion; values stored
as `{"v": …}`; cached behind a version key bumped on write; every change audited old → new; scope cascade
user → tenant → platform → code default (the tenant level stays inert behind a resolver hook:
[ADR-0011](../adr/0011-no-organisation-in-core.md) put no organisation in core).

*Owner decisions, 2026-10-22:*
- **Defaults:** code defaults resolve live, with a snapshot test (CONFIGURATION pending #2).
- **Unknown keys:** an unregistered read raises everywhere (#8).
- **Tenant level:** inert (#3).
- **Scope:** backend only (engine, model, service, CLI, admin API). The admin screen is a later task.
- **What moves:** only `REAUTH_ACTIONS` and `REAUTH_WINDOW_MINUTES` move from env into the registry.
  LOCKOUT, the session cap and retention move once an env → registry prefill exists. Supersedes the
narrower `core_setting` of `AUTH_BLUEPRINT.md` § 3.13 — reconcile the two in the same PR.

**Done when:** re-running `sync_settings` keeps an admin-edited value; `"false"` coerces to `False` and `"yes"` is
refused; an unregistered key cannot be written; a test fails on any registered key that no code outside the
settings app reads.

### 5.4 — Feature flags and guard modes ⬜
`FeatureFlag` with kill-switch-first resolution (disabled beats targeting; unknown key is off; no
`default=True` parameter exists), owner and expiry; a `GuardMode` helper for `off · log_only · enforce`.

**Done when:** the resolution order is pinned by tests; a flag past its expiry fails a test; the flags a user
sees are exposed on `/me`; shipping a new guard at its default changes no response (a test proves it).

### 5.5 — Vocabularies, locale, currency and time ⬜
A `Lookup` base (stable non-editable key, editable label, `is_active`, order) with request-time membership
validation; platform / tenant / user settings for locale, currency, timezone and formats; storage in UTC and
ISO-8601 on the wire.

**Done when:** an admin can add a lookup value with no deploy; a deactivated value is refused on new writes but
still renders on old rows; the API never returns a display-formatted date.

### 5.6 — Anti-hard-coding scans ✅
`tests/architecture/` scans for ISO-4217 and IANA timezone literals, role-name string literals and secret-shaped
`env()`/`os.environ` reads outside settings — each with a ratchet allow-list whose entries must still offend.

**Done when:** adding `"USD"` to a service fails a test that names the file and line.

*Done 2026-10-22* (pulled ahead of 5.3–5.5: tests only, no migration).
- **Shared helpers:** `tests/architecture/sources.py` is one scope walker for every scan (platform
  apps, `project/`, plugins, `config/`, `scripts/`, `frontend/src`; tests, migrations and fixtures
  excluded by path). `_ratchet.py` is the two-way ratchet, keyed by `path::value` and never by
  line, with a reason required per entry.
- **The guards:**
  - `test_no_locale_literals.py` checks ISO-4217 codes against `core/data/iso4217.txt` and
    Area/Location zones against `zoneinfo`, in Python ASTs and TS/TSX literals.
  - `test_no_role_name_literals.py` catches `has_role("…")`, `role.name == "…"`, `Role.objects.get(name=…)`
    and `role__slug=` / `groups__name=`.
  - `test_secret_env_reads.py` catches credential-shaped `os.environ` / `getenv` / `env()` reads
    outside `config/settings*.py`, resolving module-level constant keys.
- **Positive controls:** each guard has a `test_catches_*`. Done-when proven on the real tree: a
  probe `"USD"` in `backend/core/` failed with
  `backend/core/zz_probe_service.py:2: USD`.
- **First real catch:** `bootstrap_admin` looked its role up by the literal `"administrator"`. It
  now uses `rbac.services.ADMINISTRATOR`.
- **Allow-list:** one entry, `BOOTSTRAP_ADMIN_PASSWORD`, a one-shot CLI input.
- **Not built:** the BCP-47 locale-tag check (no locale settings exist until 5.5), and a vitest
  twin (there is no frontend test runner; the TS literals are scanned from Python instead).

---

## Phase 6 — observability and data foundations

*Specs: [`OBSERVABILITY.md`](../system-design/OBSERVABILITY.md), [`DATA_LIFECYCLE.md`](../system-design/DATA_LIFECYCLE.md),
[`DOMAIN_PRIMITIVES.md`](../system-design/DOMAIN_PRIMITIVES.md), [`JOBS_AND_INTEGRATIONS.md`](../system-design/JOBS_AND_INTEGRATIONS.md) § encryption.*

### 6.1 — Request id, structured logs, one scrubber ✅
**Done 2026-10-11 (pulled forward):**
- `core/observability/request_id.py`: `MIDDLEWARE[0]`, validated, trusted only behind a proxy,
  reset on `request_finished` (never in `finally`);
- `core/observability/logging.py`: JSON in production with allow-listed fields, a context filter
  on every handler, one traceback per 500, library loggers pinned;
- `core/observability/scrub.py` (the junior's): one scrubber;
- `core/api/exceptions.py`: request ids in error bodies, 500 → `server_error`, validation logged
  as codes.

The done-when is met by `tests/observability/` (canary with a positive control, and the streaming
test that catches the reset-in-finally bug). **Not yet:** Celery/command ids (no Celery),
registered module log fields, a request id in every *view-built* error envelope (only
exception-built ones carry it today), and the frontend scrubber.
Validated `X-Request-ID` in a contextvar set first and reset only after the response is built; JSON logs in
production (enforced by 5.1); one scrubber used by logging and Sentry. Closes **DB-9**.

**Done when:** a 500 body and its log line carry the same request id; a canary password sent through a normal
and a failing-validation request appears in no log line.

### 6.2 — Health in three rungs and data-plane checks ⬜
`/api/health/live` (no I/O), `/api/health/ready` (DB + cache, timeouts, no third parties, throttle-exempt),
`/api/health/components` (permission-gated); a registry of data-plane checks for required rows. Closes **DB-11**.

**Done when:** `ready` answers 503 with the database stopped while `live` answers 200; a deliberately broken
check degrades to `warn` instead of raising.

### 6.3 — Encryption service ⬜
`FIELD_ENCRYPTION_KEYS` (MultiFernet, newest first, separate from `SECRET_KEY`), a startup self-test, explicit
encrypt/decrypt functions, masking, and `rotate_encryption`. ⚠️ **If Phase 1 has not yet stored an MFA secret in
production, do this before it does** — it replaces the single-purpose MFA key.

**Done when:** rotating `SECRET_KEY` leaves every encrypted value readable; adding a new key and running
`rotate_encryption` re-encrypts; a decrypt failure raises and never returns ciphertext.

### 6.4 — Audit engine to spec ⬜
Extend the Phase 1 activity log with field diffs (secrets masked at any depth), source/via and CLI provenance,
batch id, `status_changed`, structural read-only and a streamed export.

**Done when:** an update records only changed fields with FK names and choice labels; a management command's
writes are attributed to the command, the OS user and the host; no write route exists on the log.

### 6.5 — Money and invariants ⬜
`core.money` (Decimal + currency, one quantisation helper, one rounding mode) and the invariant pattern: a
`clean()` validator plus a DB constraint plus an `IntegrityError` mapping.

**Done when:** a source scan fails on a `FloatField` or float serializer field named like money; a test proves a
`QuerySet.update()` that bypasses `clean()` is still refused by the database.

---

## Phase 7 — jobs, events, integrations and notifications

*Specs: [`JOBS_AND_INTEGRATIONS.md`](../system-design/JOBS_AND_INTEGRATIONS.md),
[`NOTIFICATIONS_AND_ALERTING.md`](../system-design/NOTIFICATIONS_AND_ALERTING.md).*

### 7.1 — Celery, the job registry and queue invariants ⬜
Jobs declared in the registry and synced into beat in `post_migrate`; `task_create_missing_queues=False`; ids-only
payloads dispatched `on_commit`. Closes **DB-16**.

**Done when:** a test fails if any declared queue has no worker in the compose file, or any beat entry names an
unregistered task; `auth_cleanup` runs from beat, not cron.

### 7.2 — Job-run monitor and the doctor umbrella ⬜
`JobRun` recorded from Celery signals (never raising, own connection); health states
`disabled · never_run · failing · overdue · ok` and "worker seen recently"; `manage.py doctor` running every
registered doctor with `--json` and exit codes.

**Done when:** stopping the worker turns the monitor red within three intervals while the failed-jobs count stays
zero; `doctor` exits non-zero on a planted problem.

### 7.3 — Outbox, reconcilers and locks ⬜
Transactional outbox (unique dedupe key, `SKIP LOCKED` leases, stale-lease recovery, `unknown` state); a
`Reconciler` base; single-flight locks with short TTLs; the open-findings queue.

**Done when:** killing a worker mid-send leaves the row `unknown`, not re-sent; a rolled-back transaction leaves
no outbox row.

### 7.4 — Safe outbound HTTP and the non-production guard ⬜
One HTTP client factory (timeouts, retries honouring `Retry-After`, redaction, private-range refusal, per-target
breaker); provider error mapping; outside production an allow-list transport answering 423 and mail redirected to
one test recipient.

**Done when:** a request to a private address is refused before connecting; in development a non-allow-listed
POST gets 423 and no mail leaves the machine except to the test recipient.

### 7.5 — The retention engine ⬜
`registry.retention` policies with age **and** row caps, batched deletes, opt-in for evidence tables, floors,
`--status` / `--dry-run`. `auth_cleanup` becomes one caller.

**Done when:** `--dry-run` reports counts and deletes nothing; a retention value of `0` is clamped to the floor; the
audit log is untouched unless named explicitly.

### 7.6 — Webhooks, outbound and inbound ⬜
Signed `timestamp.body`, SSRF guard at write **and** send, no redirects, 4xx permanent, backoff, breaker, delivery
log with redeliver and send-test, emitted through the outbox; inbound verification with DB idempotency.

**Done when:** a test fails if any catalogue event has no emitting call site, and fails — not skips — if it finds
no events at all.

### 7.7 — Notifications ⬜
Purposes registry with admin routing, channel adapters, the event × channel matrix with per-user preferences,
the in-app store (per-user read, shared resolve, digest upsert) and email templates.

**Done when:** a caller can notify with no destination in code; a failing channel never fails the save; "send
test" works for every route.

### 7.8 — Ops alerting ⬜
One dispatcher with a DB ledger, incidents announced once and recovered once, quiet hours with a single release
summary, and a twice-daily digest.

**Done when:** a flapping check produces one incident message and one recovery message, and cooldowns survive a
cache clear.

---

## Phase 8 — the frontend platform

*Spec: [`FRONTEND_PLATFORM.md`](../system-design/FRONTEND_PLATFORM.md). Depends on 1.1 (auth) and 1.4 (`/me`).*

### 8.1 — Transport, typed errors and the data layer ⬜
One transport module with typed errors and `retry_after` handling; ESLint bans `fetch` elsewhere; one data/cache
layer (decide first — `PLATFORM_BLUEPRINT.md` § 6); `useApiQuery` / `useApiList` / `usePagedQuery` with the
load-state contract.

**Done when:** an AST ratchet test fails on a new `useEffect` + `setLoading` fetch in a page; a failed list fetch
renders an error, never an empty state.

### 8.2 — Bootstrap, permissions, navigation and the session marker ⬜
`/api/me/bootstrap`; a fail-closed permission provider on *effective* permissions; server-built navigation that is
also the route gate (default-deny); the `Path=/` session marker cookie. Closes **DB-20**.

**Done when:** a page with no navigation entry is refused and a test walking `app/**/page.tsx` fails on it; a
signed-in user whose access token has expired is refreshed, not bounced.

### 8.3 — Design system and the module contract ⬜
Semantic tokens with foreground pairs, dark mode, the Index · Form · Show shells, the standard DataTable and the
mandatory primitives — built against the Users module of 1.5 as the reference.

**Done when:** the token-completeness test passes in both themes; the Users module uses only the shells.

### 8.4 — i18n, formatters and contract generation ⬜
A translation layer with per-plugin catalogues; formatters driven by bootstrap locale/currency/timezone;
OpenAPI → TypeScript types plus exported enums and permission codes, each with a drift check. Closes **DB-4**.

**Done when:** changing a serializer field without regenerating fails CI; a hard-coded currency formatter in a
page fails lint.

### 8.5 — CSP and runtime branding ⬜
Per-request nonce CSP, Report-Only first with enforcement flipped by a runtime variable; runtime brand identity
with a validated colour grammar and a backend contrast solver.

**Done when:** enforcing the CSP needs a restart, not a rebuild; a brand colour failing WCAG AA is refused with the
measured ratio and a passing suggestion.

---

## Phase 9 — platform completeness

*Before the second product. Specs: [`EXTENSIBILITY.md`](../system-design/EXTENSIBILITY.md),
[`API_PLATFORM.md`](../system-design/API_PLATFORM.md), [`DATA_LIFECYCLE.md`](../system-design/DATA_LIFECYCLE.md),
[`DOMAIN_PRIMITIVES.md`](../system-design/DOMAIN_PRIMITIVES.md), [`OPERATIONS.md`](../system-design/OPERATIONS.md),
[`ENGINEERING_PRACTICES.md`](../system-design/ENGINEERING_PRACTICES.md).*

### 9.1 — The full registry catalogue and plugin lifecycle ⬜
Every registry in `EXTENSIBILITY.md` with the uniform contribution shape; the soft-disable contract; the versioned
SDK facade; service contracts. Needs Phase 3. Closes **DB-18**, **DB-22**.

**Done when:** disabling a plugin hides its nav, routes, jobs, search sources and help pages without touching its
data; `manage.py check` passes with every plugin removed from `INSTALLED_APPS`.

### 9.2 — API platform ⬜
The shared list pipeline (required pk tiebreak, unknown filters rejected), the error-code catalogue, the 429
contract, content-sniffed uploads with private file serving, and machine callers once **DB-21** is decided.

**Done when:** a list endpoint sorted on a non-unique column never repeats or drops a row across pages; an upload
renamed to `.png` but containing HTML is refused.

### 9.3 — Data lifecycle ⬜
Soft delete with partial unique constraints and the recycle bin; state-transition history; provenance; every
listable model registered for scoping, with write-path narrowing.

**Done when:** a test fails if any model with a tenant or owner field is not registered for scoping; a user who
cannot see a row gets 404 on `PATCH` to it.

### 9.4 — Domain primitives ⬜
Document sequences (peek vs reserve), the state-machine helper, the business calendar, bulk actions, the
import/export registry.

**Done when:** two concurrent reservations on a fresh database mint different numbers; a bulk action over "all
matching" touches exactly the rows the list shows.

### 9.5 — Operations ⬜
Release images, the deploy driver, verified backups, restore with `config_snapshot`, infrastructure policy tests,
the first-run wizard.

**Done when:** a deploy whose backup fails stops before migrating; a restored dump from another environment comes
up with its schedules and integrations disabled.

### 9.6 — Engineering practice ⬜
`BUG_CLASSES.md` in the PR template; the upgraded ADR template; generated folder indexes and a doc link test;
`CHANGELOG.md` with upgrade notes; per-app idempotent `seed_demo`. Closes **DB-13**.

**Done when:** a broken relative link in `documentation/` fails CI; `seed_demo` run twice creates each demo row
once.

---

## Phase 10 — the real test

*Renumbered from Phase 5 on 2026-09-29, when the platform-service phases were inserted before it.*

### 10.1 — Build a second product on it ⬜
**Nothing proves a core is reusable until something else is built on it.** Whatever hurts the second
time is the design flaw. It is far cheaper to find at product two than at product five.

---

## Not in any phase — do these when they come up

- **DB-7** — refuse `DEBUG=True` and placeholder secrets when not in development → now **5.1**
- **DB-8** — production security settings (`SECURE_SSL_REDIRECT`, secure cookies, HSTS)
- **DB-9** — `LOGGING` configuration with request correlation → now **6.1**
- **DB-11** — a readiness probe that actually checks the database → now **6.2**
- **DB-4** — generate frontend types from `/api/schema/` → now **8.4**
- **DB-3** — `mypy` + `django-stubs`
- **DB-13** — a `seed` management command → now **9.6**
