# Operations

**How a DjangoBaseX product is set up, built, deployed, backed up, restored and kept alive —
environments, the one-command setup, the first-run wizard, release images, the deploy driver and
its rolling swap, expand/contract migrations, backups and restore, PgBouncer and Postgres, the
reverse proxy, container hygiene, infrastructure policy tests, and the production build of the
frontend.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

---

## Scope — read first

[`DEPLOYMENT.md`](DEPLOYMENT.md) stays the **gap analysis and pre-deploy checklist**: which settings
change per environment, what blocks a first deploy, what `check --deploy` names. This file is the
**machinery** that closes those gaps. Where the two overlap, this file is the more specific one and
§ 21 lists every sentence in `DEPLOYMENT.md` that should change to match.

**Owns:** environment isolation (compose project names, staging parity, data never flowing
production → development) · `scripts/setup.sh` · the first-run setup wizard · the development
sign-in hint · release images · the deploy driver and the rolling swap · expand/contract migration
rules and their linter · backups, verification and restore procedure · the test-database guard ·
connection pooling and Postgres server settings · the optional log database alias · the reverse proxy
reference config · container hygiene · infrastructure policy-as-tests · the Next.js production build
order · shared-environment etiquette · the release git-flow option.

**Does not own:**

| Topic | Owner |
|---|---|
| `APP_ENV` values, `is_production_like()`, boot refusal, env-as-prefill, restore *settings* semantics | [`CONFIGURATION.md`](CONFIGURATION.md) |
| Health endpoints, logs, metrics, alert rules, doctors | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| Celery configuration, job registry, schedules, non-production outbound guard | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| Frontend runtime config, CSP, session marker cookie, route gate | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| Upload purposes and size policy | [`API_PLATFORM.md`](API_PLATFORM.md) |
| CI pipeline, test harness, semver and release process detail | [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) |
| The routine of writing a migration | [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md) — this file adds the rules for migrations that must survive a rolling deploy |
| Same-site cookies, CORS, client IP | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) Ch. 17 — this file configures the proxy that makes them true |

> ⚠️ **Tier 2 is not optional for a production deploy.** Tiers order the *core's* build. Every
> Tier 2 section below — release images, the deploy driver, backups, the proxy — is a blocker for
> the first internet-facing deploy of *any* product, and belongs in [`DEPLOYMENT.md`](DEPLOYMENT.md)
> § 0's table when that product gets there.

---

## 0. The rules in one screen

1. **One environment, one compose project name** — separate containers, volumes and networks; staging is production settings plus a marker — [§ 1](#1-environments--tier-1--core)
2. **Production data never flows into development.** Seed instead; if a dump must move, it is sanitised by registered sanitisers first — [§ 1](#1-environments--tier-1--core)
3. **`setup.sh` is idempotent, never overwrites a secret, picks *and persists* free ports, and ends by proving the app answers** — [§ 2](#2-the-one-command-setup--tier-1--core)
4. **Generated secrets are hex or URL-safe.** A `$` in a secret is a reference to another variable — [§ 2](#2-the-one-command-setup--tier-1--core)
5. **The setup wizard is behind a one-time token, is sealed once complete, and writes everything in one transaction** — [§ 3](#3-the-first-run-setup-wizard--tier-2--core)
6. **Images are built only from a clean, exact, annotated tag, smoke-tested inside the image, and never rebuilt on a server** — [§ 5](#5-release-images--tier-2--core)
7. **Production compose references versioned images only** — no `build:`, no `:latest`, no source bind mounts, no reload — [§ 5](#5-release-images--tier-2--core)
8. **Deploy order is fixed:** validate inside the new image → pull → verified backup → migrate from the new image while the old serves → workers → rolling web swap → proxy → verify — [§ 6](#6-the-deploy-driver--tier-2--core)
9. **Every remote command runs under `pipefail`; migrate hard-fails; nothing is `|| true`** — [§ 6](#6-the-deploy-driver--tier-2--core)
10. **Start the new instance beside the old, gate on ready, retire the old by container id.** Never scale down to reconcile — [§ 7](#7-the-zero-downtime-rolling-swap--tier-2--core)
11. **Every migration is expand/contract, because old code runs against the new schema on every deploy.** A linter enforces it; contract steps carry an explicit marker — [§ 8](#8-expandcontract-migrations--tier-1--core)
12. **Migrate takes a `lock_timeout`, connects directly (never through a transaction pooler), and never rewrites operator-authored content** — [§ 8](#8-expandcontract-migrations--tier-1--core)
13. **A backup is not a backup until it is verified, recorded, copied off the box and watched for freshness** — [§ 9](#9-backups--tier-2--core)
14. **Restore reads the dump before it drops anything, drops and recreates rather than `--clean`, and keeps the target's own connections — with every imported schedule off** — [§ 10](#10-restore--tier-2--core)
15. **The test runner refuses any database whose name is not a test database** — [§ 11](#11-the-test-database-guard--tier-1--core)
16. **Behind a transaction pooler: `CONN_MAX_AGE=0`, no server-side cursors, no prepared statements, transaction-scoped advisory locks only** — [§ 12](#12-connection-pooling-and-postgres--tier-2--core)
17. **The proxy *sets* `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Request-ID`; it never appends** — [§ 14](#14-the-reverse-proxy--tier-2--core)
18. **Only the edge proxy publishes a port. Every secret is `${VAR:?}`** — [§ 15](#15-container-hygiene--tier-1--core)
19. **Infrastructure files are tested like code** — [§ 16](#16-infrastructure-policy-as-tests--tier-1--core)
20. **Frontend production build: migrate → seed → start API → build; clear the fetch cache first; assert baked values with a grep that can fail** — [§ 17](#17-the-nextjs-production-build--tier-2--core)

---

## 1. Environments — **Tier 1 · Core**

**What.** The rules that keep development, test, staging and production from touching each other:
identity, naming, isolation and the direction data is allowed to flow. `APP_ENV` itself —
its values, and the fail-closed `is_production_like()` predicate — is
[`CONFIGURATION.md`](CONFIGURATION.md)'s.

**Why.** Hand-typed compose commands against the wrong overlay, two stacks sharing a volume, a
staging box that is "production except for a few settings nobody remembers", and a production dump
restored into staging **with its working credentials and its schedules running** — each of these has
happened, and each is a naming or direction rule nobody wrote down.

**Rules.**

- **One compose project name per environment and per checkout.** `COMPOSE_PROJECT_NAME =
  <slug>-<env>` (`acme-dev`, `acme-staging`, `acme-production`), derived and validated by **one**
  function in `scripts/lib/project.sh` (lower-case `[a-z0-9-]`, non-empty, ≤ 40 chars). It
  namespaces containers, volumes and networks, so `docker compose down -v` in one environment
  cannot touch another's data.
- **A second checkout (a git worktree) is a second stack.** The development slug includes the
  checkout directory name, ports are chosen per stack (§ 2), and the auth cookie names already
  derive from the slug ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12) — cookies ignore the port, so
  two stacks sharing cookie names on `localhost` log each other out.
- **Staging = production settings + a marker.** There is no `settings/staging.py`. Staging runs
  the production image and the production settings with `APP_ENV=staging`. The **only** permitted
  differences are an allow-list: hostnames, secrets, `APP_ENV`, scale, and the non-production
  outbound guard ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)). A test diffs the key sets
  of `deploy/env/staging.env.example` and `deploy/env/production.env.example` and fails on any key
  outside the allow-list.
- **Development pins production versions.** `docker-compose.yml` pins Postgres, Redis and the proxy
  to the production major/minor and the production server settings (§ 12) — a development database
  whose behaviour differs from production's is a test suite proving things in the wrong place
  (`TECH_DEBT` **DB-12**).
- **The scheduler is off in development by default.** Beat sits behind a compose profile
  (`--profile scheduler`). Jobs that only make sense against live data must not fire from a laptop;
  the outbound guard is the second line.
- **Production data never flows to development.** Development gets seeded demo data
  (`manage.py seed --demo`, per-module seeders that go through services). When a real dump genuinely
  must move down (a staging reproduction), it passes through `manage.py sanitise_snapshot` first,
  driven by **registered sanitisers** — `registry.sanitisers.register(User, email=pseudonymise_email,
  password=make_unusable)` — which also truncates sessions, tokens and login attempts, clears
  integration credentials and disables every schedule (§ 10). `db-restore.sh` refuses a dump whose
  recorded source is production into a non-production target unless `--sanitise` is given.
- **A distinct encryption key per environment.** Then a production ciphertext restored into staging
  fails to decrypt — **closed** — instead of handing staging working production credentials.
  Decrypt failures must raise, never return the ciphertext ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).

**Django + Next shape.** `deploy/env/{development,staging,production}.env.example` (blank secrets),
`scripts/lib/project.sh::project_name <env>`, `manage.py seed --demo`,
`manage.py sanitise_snapshot`, `registry.sanitisers`.

**Enforced by.** `tests/infra/test_env_parity.py` (staging vs production key allow-list) ·
`test_project_name.sh` (bats or pytest-subprocess: normalisation, rejection of empty/invalid) ·
`test_sanitisers_cover_pii_models.py` (every model with a field named like an email, phone or
address has a registered sanitiser or an explicit exemption with a reason).

**Configurable, not hard-coded.** `APP_ENV` · `COMPOSE_PROJECT_NAME` (derived, overridable) ·
`APP_SLUG` · sanitisers are registry entries.

---

## 2. The one-command setup — **Tier 1 · Core**

**What.** `scripts/setup.sh` ([`BUILD_ORDER.md`](../planning/BUILD_ORDER.md) **4.1**): from a fresh
clone to a signed-in application in one command, on Docker, with a non-Docker path for machines
without it. [`VISION.md`](../VISION.md)'s first test is *"clone it, run one script, sign in"*; this
is that script.

**Why.** First-run failures are where evaluations end. The common ones are known: a port already in
use; a rerun that reports a URL nothing listens on because the port it chose last time was not
saved; a generated database password containing `@` that breaks `DATABASE_URL`; a half-finished run
that cannot be resumed; a script that says "done" before anything answers.

**Rules — the flow.**

| # | Step | Detail |
|---|---|---|
| 1 | **Preflight** | Docker present, **compose v2** (`docker compose version`, not `docker-compose`), daemon running, free disk above a floor. Each failure prints the fix (*"Docker daemon not running — start Docker Desktop, then re-run ./scripts/setup.sh"*), never a stack trace |
| 2 | **Identity** | Slug from the directory name, normalised by the § 1 function; confirm on a TTY, accept on `--yes`/`CI` |
| 3 | **Ports** | For each published port (`WEB_PORT`, `API_PORT`, `DB_PORT` loopback-only, opt-in service ports): if `.env` already has one, **check it is still free** (another stack may have taken it); otherwise probe the preferred port and walk upward to a free one. **Persist** the choice in `.env` — a rerun must report the URL something listens on |
| 4 | **Env files** | Create from `deploy/env/development.env.example` only if absent; **fill only keys that are empty or equal a known placeholder**; never overwrite an existing value. `chmod 600`. **Refuse to create a staging or production env from a template** — the development template has `DEBUG=True`, and an env file copied from it is how that reaches production |
| 5 | **Secrets** | Generated by the backend's own `manage.py generate_secret --kind {django,jwt,fernet,hex}` so the format is owned by the code that reads it. **Hex for database passwords** (no `@#/:%` → `DATABASE_URL` needs no percent-encoding); **URL-safe** (`secrets.token_urlsafe`) for signing keys — never Django's `get_random_secret_key()` (§ 21) |
| 6 | **Opt-in services** | `--with-mailcatcher`, `--with-objectstore` (bucket pre-provisioned). **Sticky**: the choice is persisted (`DBX_WITH_MAILCATCHER=1`) so a rerun keeps it; an explicit `--without-*` always wins |
| 7 | **Start dependencies** | `docker compose up -d --wait db cache` — wait on their healthchecks, not a `sleep` |
| 8 | **Migrate** | `docker compose run --rm backend python manage.py migrate` — `run --rm`, never `exec` (the entrypoint that rewrites `DATABASE_URL` for the container network runs only on `run`) and **never auto-migrate on container start** (§ 5) |
| 9 | **Seed** | Core seeders (catalog, system roles, settings defaults) are fatal on failure; module seeders are non-fatal and print the exact rerun command |
| 10 | **First account** | `bootstrap_admin` — in development with the development password and the sign-in hint (§ 4); elsewhere, prompted |
| 11 | **Start the apps** | `docker compose up -d --wait` |
| 12 | **Prove it** | Poll `/api/health/ready/` and the frontend sign-in page until both return 200, with a timeout that prints the failing service's last log lines |
| 13 | **Say what next** | Print the URLs (app, API docs, mail catcher UI), the admin account's email, and *"Next: documentation/NEW_PROJECT.md"* |

**Rules — behaviour.**

- **Idempotent and resumable.** Every step checks whether it is already done. A run interrupted at
  step 8 finishes from step 8.
- **Non-interactive when `CI` is set or there is no TTY** — defaults are taken, prompts become
  failures with the flag that would answer them.
- **Named volumes, not bind mounts, for database data.** Postgres writes its data directory as its
  own uid; a bind-mounted `data/` then cannot be deleted by the developer without `sudo`, and
  `rm -rf data/` "fails for no reason". The only destructive command is `scripts/setup.sh --reset`,
  which names the project and volumes and requires the project name typed back
  ([`AGENTS.md`](../../AGENTS.md) rule 4).
- **Without Docker:** `uv sync`, `manage.py migrate`, seeders, `bootstrap_admin`, `npm ci`,
  `.env`/`.env.local` written by the same fill-only-empty logic — the same guarantees, a shorter
  path.
- **Rename is part of setup, not a second checklist.** The identity keys ([`CONFIGURATION.md`](CONFIGURATION.md)
  project identity) are filled from the slug, so [`NEW_PROJECT.md`](../NEW_PROJECT.md)'s manual
  rename table shrinks to the files that cannot be generated.

**Django + Next shape.** `scripts/setup.sh` sourcing `scripts/lib/{log,preflight,ports,env,
secrets,compose,health}.sh`; `manage.py generate_secret`; `manage.py seed [--demo]`.

**Enforced by.** `tests/infra/test_setup_script.py` running the script against a sandbox directory
with a stub `docker`: rerun keeps every existing secret byte-for-byte; a taken persisted port is
detected; a staging template is refused; `bash -n` and `shellcheck` clean. CI runs the real script
once per week on a clean runner (a setup script nobody runs from scratch rots silently).

**Configurable, not hard-coded.** Preferred ports and the disk floor are `.env` keys with defaults;
the opt-in services are flags persisted in `.env`.

---

## 3. The first-run setup wizard — **Tier 2 · Core**

**What.** A guided first-run flow in the product itself, for installs where a person — not a script —
configures identity, the first administrator, mail, sign-in and storage. It complements
`bootstrap_admin` ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 19.1): the CLI serves headless and
scripted installs, the wizard serves a person with a browser. **Both call the same service**, and
whichever completes first seals the other.

**Why.** No default credentials ever exist, and a fresh install is guided instead of documented.
The wizard is also the right home for connectivity testing: an operator should learn their SMTP
password is wrong *before* the first password-reset email silently fails.

**Rules.**

- **Behind a one-time `SETUP_TOKEN`.** Generated at first boot if not provided, **stored hashed**.
  In development it is printed to the console; **in production it is never written to a log** — the
  entrypoint writes it to `setup-token.txt` (mode `0600`) in the data volume and logs only *"setup
  token written to <path>"*. A token printed on every container start is a credential in the log
  aggregator.
- **Token verification** (`POST /api/setup/verify-token/`) is throttled like a login and, on
  success, sets a short-lived signed setup cookie scoped to `Path=/api/setup/`.
- **Sealed once complete.** `/api/setup/*` except `status` answers **404** afterwards — not 403, so
  the endpoint is not an oracle for "this install was set up by a wizard". Next's `proxy.ts`
  redirects `/setup` to `/`.
- **Until complete, the install is gated.** `SetupRequiredMiddleware` answers every API route with
  `503 {"error": {"code": "setup_required"}}` except an **always-allowed** list: the two public
  health rungs (already answered earlier, [`OBSERVABILITY.md`](OBSERVABILITY.md) § 6),
  `/api/setup/*`, the public frontend-config endpoint, static assets. Next's proxy redirects every
  page to `/setup`. The always-allowed list is one constant with a test — a missing entry is how a
  fresh install's service worker, manifest or health check breaks.
- **Connectivity tests do real round trips.** `POST /api/setup/test/{database,email,sso,storage}/`:
  database — connect, `SELECT version()`, confirm the role can create a table in a transaction it
  rolls back; email — connect, STARTTLS, authenticate, send to an address the operator types;
  SSO — fetch the discovery document and probe the token endpoint with the **exact** redirect URI,
  distinguishing "wrong client secret" from "redirect URI not registered"; storage — put, get and
  delete a random-keyed probe object, then fetch a presigned URL for it the way a browser would.
- **Every connectivity test goes through the SSRF-safe HTTP client**
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)). A wizard that fetches operator-supplied
  URLs is an SSRF surface on an unauthenticated install.
- **All writes in one transaction.** `services.complete_setup(data)` writes identity settings, the
  first administrator (through the same service `bootstrap_admin` uses), mail, storage and SSO
  configuration inside one `transaction.atomic()`, marks setup complete, invalidates the token and
  writes an `ActivityLog` row. A half-completed setup is not a state.
- **Env values only prefill.** `SMTP_*`, `S3_*` and friends pre-fill the wizard's fields; the saved
  rows are the runtime source of truth ([`CONFIGURATION.md`](CONFIGURATION.md) env-as-prefill).

**Django + Next shape.** Settings-registry key `core.setup.completed_at`; `core/setup/` with
`views.py`, `services.py`, `diagnostics.py`; frontend `src/app/setup/` (a public route group).
`SETUP_WIZARD_ENABLED` defaults to `True`; a product that only ever installs by script turns it off
and relies on `bootstrap_admin`.

**Enforced by.** `test_setup_wizard.py`: `test_sealed_after_complete_returns_404` ·
`test_complete_setup_is_atomic` (a failure in the last write leaves nothing) ·
`test_token_never_logged_in_production` (log capture) · `test_always_allowed_paths` ·
`test_bootstrap_admin_and_wizard_seal_each_other` · `test_connectivity_tests_use_ssrf_client`
(private-address target refused).

**Configurable, not hard-coded.** `SETUP_WIZARD_ENABLED` · `SETUP_TOKEN` (optional; generated if
absent) · `SETUP_TOKEN_PATH` · which steps appear is a registry (`registry.setup_steps`) so a module
can add one (a payment provider, a tenant) without a core edit.

---

## 4. The development sign-in hint — **Tier 2 · Core**

**What.** On a development install, the sign-in page shows the seeded development credential — for
exactly as long as it still works.

**Why.** The seeder's printed password scrolls away, and for someone evaluating the core, "I cannot
sign in" is where the evaluation stops. But advertising a credential that no longer works is worse
than showing none, and advertising one anywhere but development is a vulnerability.

**Rules.**

- **Three conditions, one auditable function** — `core/dev_credentials.py::sign_in_hint()`:
  1. `APP_ENV == "development"` — **equality**, not `!= "production"`, so staging and every
     unknown value are excluded;
  2. `DEV_SIGNIN_HINT_ENABLED` (default `True` in development);
  3. some **active superuser** — found by the flag, never by an email convention — whose password
     still verifies against the committed `DEV_SEED_PASSWORD`.
- **Self-cancelling.** The moment that password changes, the hint disappears. Checks every matching
  superuser (bounded to a few, cached 30 s — hashing is deliberately slow), not only the oldest: a
  real bug found by its own tests was checking the oldest root account when a newer one still had
  the seeded password.
- **The route always exists and answers 404** when there is no hint. It is in the `PUBLIC_ROUTES`
  ledger with a reason; mounting it only in development would make the ledger name a route that
  does not exist in production and fail `dbx.E007`.
- **`bootstrap_admin --dev`** uses `DEV_SEED_PASSWORD` only when `APP_ENV == "development"`;
  anywhere else it prompts, as [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 19.1 requires. The boot
  audit refuses production if any active account's password verifies against it — a cheap check,
  run once at the deploy validate step rather than on every boot.
- `DEV_SEED_PASSWORD` is obviously fake and committed; it is not a secret, which is exactly why it
  must never work outside development.

**Django + Next shape.** `GET /api/auth/dev-hint/` → `{email, password}` or 404; the sign-in page
fetches it client-side and renders a dismissible notice.

**Enforced by.** `test_dev_credentials.py`: `test_no_hint_in_production_even_with_seed_password` ·
`test_no_hint_in_staging` · `test_hint_disappears_when_password_changes` ·
`test_newer_superuser_with_seed_password_still_hinted`.

**Configurable, not hard-coded.** `DEV_SIGNIN_HINT_ENABLED` · `DEV_SEED_PASSWORD` is a constant in
code, not an env var — an env var can be set in production.

---

## 5. Release images — **Tier 2 · Core**

**What.** The immutable artefacts a deploy runs: one backend image (web, workers, beat and
management commands share it) and one frontend image per release, built only from a tag, labelled,
smoke-tested **inside the image** before they are pushed, and referenced by version from production
compose.

**Why.** A real incident: production ran the development server with auto-reload on a bind-mounted
source tree; a `git pull` hot-swapped the code about ninety seconds before the migrations it
depended on had run, and every request in between failed. "What is running in production" must be
an answer you can read off a label, not a directory you have to diff.

**Rules — building.**

- **Only from a clean, exact, annotated tag.** `scripts/release/build.sh <version>` refuses unless
  the version matches the release pattern (§ 19), `git status --porcelain` is empty (untracked files
  included), and `git describe --exact-match --tags HEAD` equals the version.
- **OCI labels:** `org.opencontainers.image.version`, `.revision` (full commit SHA), `.created`,
  `.title`. `APP_VERSION` is baked as an env var from the same value.
- **Smoke-test inside the image before push.** With a synthetic production-shaped env (valid-looking,
  throwaway secrets, no database):
  `python -c "import django; django.setup(); from config.celery import app; app.loader.import_default_modules()"`
  (imports the app and **every registered task module** — an import error in a task module is
  otherwise found by the first worker that receives that task) then
  `python manage.py check --deploy --fail-level WARNING`, and assert `APP_VERSION` equals the tag.
- **Base images pinned by digest** (`python:3.12-slim@sha256:…`), refreshed deliberately by a
  dependency PR, never by whatever `:3.12-slim` means today.
- **Multi-stage.** Builder: copy the `uv` binary from its official image (pinned by digest),
  `uv sync --frozen --no-dev --no-install-project` into `/opt/venv` with `UV_COMPILE_BYTECODE=1`.
  Runtime: slim, runtime libraries only, `/opt/venv` copied in, **non-root** (`USER 10001:10001`).
- **`collectstatic` at build**, in the builder stage, with a throwaway development env — static
  files depend on no secret, and the runtime stage inherits none of those values.
- **`HEALTHCHECK` targets readiness**, `/api/health/ready/`, using a Python one-liner (the slim image
  has no `curl`). Docker's health status gates the rolling swap, so it must mean "can serve".
- **Build-time secrets via BuildKit** (`RUN --mount=type=secret,id=sentry_token …`), never `ARG`
  or `ENV` — both persist in the image layers and its history.
- **`.dockerignore`** excludes `.env*`, keys, `*.pem`, `logs/`, `.git/`, `node_modules/`, `.venv/`,
  `db.sqlite3`, `media/`.
- **The frontend image** uses `output: "standalone"` (copy `public/` and `.next/static/` into the
  standalone directory), sets `deploymentId` to `APP_VERSION` for Next's version-skew protection
  during a rolling swap, and — if server actions are used — takes a consistent
  `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY` so two instances can decrypt each other's actions.
  `NEXT_PUBLIC_*` values are baked, so the frontend image is **per environment** unless the product
  adopts runtime config ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)); § 17 covers the build.

**Rules — running.**

- **Production compose references only versioned images:**
  `image: ${IMAGE_PREFIX:?}/backend:${APP_VERSION:?}`. No `build:`, no `:latest`, no source bind
  mounts, no `--reload`, no `runserver`, no `next dev`.
- **No migration in the entrypoint.** Migrating on container start is an implicit destructive
  operation, and with two replicas it races. Migrate is an explicit deploy step (§ 6). The web
  entrypoint does run the data-plane fatal check before `exec gunicorn`
  ([`OBSERVABILITY.md`](OBSERVABILITY.md) § 7).
- **Process roles are commands, not images:** `web` (gunicorn), `worker` (Celery, one service per
  queue group), `beat` (exactly one), `frontend` (Next standalone server).

**Django + Next shape.** `backend/Dockerfile` (dev), `backend/Dockerfile.prod`,
`frontend/Dockerfile.prod`, `scripts/release/build.sh`, `deploy/compose/{base,web,worker,edge,db}.yml`.

**Enforced by.** § 16's policy tests (`test_prod_images_versioned`, `test_base_images_pinned`,
`test_non_root`, `test_no_reload_in_prod`) and `test_release_build_refuses_dirty_tree` (the script
against a fixture repo: dirty tree, untagged HEAD, lightweight tag — each refused).

**Configurable, not hard-coded.** `IMAGE_PREFIX` (the registry path — never a literal in compose) ·
`APP_VERSION` · the release version pattern (§ 19).

---

## 6. The deploy driver — **Tier 2 · Core**

**What.** `scripts/deploy/deploy.sh <version> --env <env> [--roles web,worker,beat,frontend]
[--include-db] [--dry-run] [--no-backup]` — one entrypoint, modular (`scripts/deploy/lib/*.sh`),
with a fixed step order.

**Why.** A real incident, twice in one day: containers were started before migrations ran, and for
about a minute every request touching the new column failed with "column does not exist". An
application-side "wait until the schema is at head" gate was considered and rejected — it only turns
500s into 503s. The order has to be right. Another: the driver's remote helper ran
`ssh … "cmd 2>&1 | tee -a log"` without `pipefail`, so every exit status was `tee`'s and none of its
`|| fail` guards could ever fire; and its migrate step ended in `|| true`.

**Rules — the order.**

| # | Step | Detail |
|---|---|---|
| 0 | **Identify** | Resolve host, compose project, database name, current → target version. Print them. In production on a TTY, require the project name typed back |
| 1 | **Validate** | Inside the **new** image, against the host's **real** env file (`docker run --rm --env-file <host env> <NEW image> …`): `manage.py validate_env --strict` (the env schema, [`CONFIGURATION.md`](CONFIGURATION.md) § 6 — importing settings also runs the import-time boot audit), then `manage.py check --deploy --fail-level WARNING`, then `manage.py doctor --json --only observability,settings`. New code may require keys the host does not have yet; this is the step that finds out while the old release is still serving |
| 2 | **Pull** | Every role's image. Fail here, before anything has changed |
| 3 | **Backup** | Mandatory in production: `db-backup.sh predeploy-<current>-<utc>` (§ 9), labelled with the **currently deployed** version (the dump is the old state). **A non-zero exit aborts the deploy.** `--no-backup` is refused in production |
| 4 | **Migration preflight** | `manage.py doctor --only migrations --json` from the new image: applied migrations the release does not know → **abort** (the database is ahead of the code — someone deployed another branch); unapplied list printed; contract steps present (§ 8) → require `--allow-contract` |
| 5 | **Migrate** | `docker compose run --rm --no-deps backend python manage.py migrate --noinput` from the **new** image, while the old containers keep serving. Hard-fail. Then `manage.py migrate --check` — non-zero if anything is still unapplied |
| 6 | **Workers** | Recreate worker services with the new image — Celery warm shutdown (`stop_grace_period` ≥ the longest soft time limit). **Beat: stop the old before starting the new** — two beats double-fire every schedule |
| 7 | **Web** | Rolling swap, one instance at a time, gated on ready (§ 7) |
| 8 | **Frontend** | Same swap |
| 9 | **Proxy** | `nginx -t && nginx -s reload` — config mounted as a directory (§ 14) so reload sees it |
| 10 | **Verify** | See below. A failed verify is a failed deploy, reported as such |
| 11 | **Record** | Deploy log line, `app_build_info` flips, Sentry release marked deployed. **The tag is the rollback target; a deploy without one is unfinished** |

**Rules — verify.**

- Every expected container is running and `healthy`.
- `/api/health/live/` and `/api/health/ready/` **through the public URL** (the whole chain: DNS, TLS,
  proxy, app, database), and `/api/health/components/` with the monitoring credential — no `down`,
  and `release` equals the target version.
- **A log grep** over each new container since it started, for
  `Traceback|Refusing to start|ImproperlyConfigured|Received unregistered task|OperationalError|ProgrammingError|does not exist`
  — each a class of failure that answers 200 on health and 500 on real traffic.
- **Internal ports are closed:** from the driver host, connections to the database, cache, broker and
  metrics ports on the public address must be **refused**.
- On any verify failure, dump the last 200 log lines of every new container into the deploy log
  before exiting non-zero.

**Rules — mechanics.**

- **Every remote command runs under `bash -o errexit -o nounset -o pipefail -c '…'`.** Logging to a
  file uses `… 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}"` or runs under `pipefail` — never a bare
  pipe into `tee`.
- **Nothing is `|| true`.** A step that is allowed to fail says so in a named function with a
  comment, and the driver still reports it.
- **`--dry-run`** prints the fully resolved plan (every command, in order, with the target host) and
  changes nothing.
- **Rollback = re-run with the previous tag.** It is valid because every migration in a release is
  expand-only relative to the previous release (§ 8). Restoring the database is the last resort, not
  the rollback plan.
- **The stateful tier is not touched** unless `--include-db` is passed.
- **The driver refuses to run on a dirty working tree of its own** (it is part of the release too).

**Django + Next shape.** `scripts/deploy/deploy.sh`, `scripts/deploy/lib/{remote,compose,rollout,
backup,verify,log}.sh`, `manage.py validate_env`.

**Enforced by.** `tests/infra/test_deploy_driver.py`: `bash -n` and `shellcheck` on every script;
the `--dry-run` plan snapshot asserts the step order above; `test_remote_uses_pipefail`;
`test_no_or_true` (grep with a positive-control fixture); `test_migrate_uses_new_image`;
`test_backup_failure_aborts` (a stub backup that exits 3 → the driver exits non-zero before step 4);
`test_db_not_recreated_without_flag`.

**Configurable, not hard-coded.** `DEPLOY_HOST` · `DEPLOY_LOG_DIR` · `ROLLOUT_HEALTH_TRIES` (60) ·
`ROLLOUT_HEALTH_INTERVAL` (2 s) · `VERIFY_LOG_PATTERNS` (extensible per product) ·
`VERIFY_CLOSED_PORTS`.

---

## 7. The zero-downtime rolling swap — **Tier 2 · Core**

**What.** How step 7 of § 6 replaces a web (or frontend) instance without dropping requests, on a
single Docker host with compose. An orchestrator does the same thing with different verbs; the rules
carry over unchanged.

**Why.** Two real incidents. `--force-recreate` took the proxy and the web tier down together, for a
few seconds of 502s per deploy. The fix introduced a second, subtler one: after starting a new
replica beside the old, the deploy "tidied up" with `--scale web=1` — and compose, which reconciles
by index, **recreated the survivor**, causing about 25 seconds of outage and ninety-odd 502s.

**Rules — the swap.**

1. **Start the new beside the old:** `docker compose up -d --no-deps --no-recreate --scale web=2 web`.
   Compose creates one container from the new definition and leaves the running one alone.
2. **Gate on health:** poll the **new container id** until Docker reports `healthy` (readiness,
   § 5), up to `ROLLOUT_HEALTH_TRIES × ROLLOUT_HEALTH_INTERVAL`. On timeout: dump its logs, remove
   it, exit non-zero — **the old instance never stopped serving**.
3. **Let the proxy learn it:** wait one resolver TTL (§ 14 — per-request DNS with `valid=5s`).
4. **Retire the old by container id:** `docker stop --time "$GRACEFUL" <old_id> && docker rm <old_id>`.
   **Never `--scale web=1`.**
5. **Repeat** per instance when running more than two.

**Rules — why it does not drop requests.**

- **Gunicorn drains on SIGTERM:** it closes its listening socket and gives in-flight requests
  `--graceful-timeout` to finish. `docker stop --time` must be ≥ that value.
- **New connections to the stopping instance are refused, and a refused connection is safe to
  retry for every method** — nothing was sent. `proxy_next_upstream error timeout http_502 http_503`
  retries onto the other address. For requests that *were* sent, the proxy's default already refuses
  to retry non-idempotent methods; **never add `non_idempotent`** — a retried POST is a
  double-charge.
- **Timeouts shrink inward:** database `statement_timeout` < gunicorn `--timeout` < proxy
  `proxy_read_timeout`. The innermost layer gives up first, with the most informative error, instead
  of the proxy returning a 504 that nothing logged.

**Rules — gunicorn.**

`--preload` (import once in the master: an import error fails the start instead of every worker
crash-looping; shared memory) · `--max-requests 1000 --max-requests-jitter 100` (bound slow leaks;
the jitter stops every worker recycling at the same moment) · `--graceful-timeout 30` ·
`--timeout` per the ladder above · `--worker-tmp-dir /dev/shm` (the heartbeat file on tmpfs —
on an overlay filesystem a slow `fsync` is mistaken for a hung worker) ·
`--access-logformat` with `%({x-request-id}o)s` and `%(M)s`
([`OBSERVABILITY.md`](OBSERVABILITY.md) § 1). **Multiple workers require the shared cache**
([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.4) — on a per-process cache, four workers turn a
limit of 10 attempts a minute into 40.

**Rules — what the swap demands of code.**

- **Old code runs against the new schema** for the length of the swap, and for as long as a rollback
  lasts. That is the whole reason for § 8.
- **Old frontend runs against the new API** for the same window: API changes within one release are
  additive.
- **Old workers receive tasks from new web, and vice versa:** a new task argument is optional with a
  default for one release; a renamed task keeps its old name registered as an alias for one release.

**Enforced by.** The deploy driver tests (§ 6: `test_retire_by_container_id`,
`test_no_scale_down_reconcile` — grep for `--scale web=1` with a positive control) and a staging
**soak test** in the release checklist: a load generator sending mixed GET/POST traffic through a
deploy, asserting zero 5xx.

**Configurable, not hard-coded.** `GUNICORN_WORKERS` · `GUNICORN_THREADS` · `GUNICORN_TIMEOUT` ·
`GUNICORN_GRACEFUL_TIMEOUT` · `GUNICORN_MAX_REQUESTS` / `_JITTER` · `ROLLOUT_*` (§ 6).

---

## 8. Expand/contract migrations — **Tier 1 · Core**

**What.** The rule that every schema change must be compatible with the code of the **previous**
release, the patterns that make common changes compatible, the linter that enforces it, and the
operational settings `migrate` runs under. Extends
[`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md), which covers writing a migration; this covers
surviving a deploy with one.

**Why.** In a rolling deploy (§ 7), migrations run *before* the new code starts and *while* the old
code serves. A migration that drops, renames or tightens anything the old code uses turns every
deploy into an outage window — and makes rollback impossible, because the old release cannot run
against the new schema at all. And for a **platform core**, "the previous release" includes every
product that has not taken the update yet.

**Rules — the patterns.**

| Change | Expand (release N) | Contract (release N+1 or later) |
|---|---|---|
| **Add a NOT NULL column** | Add it with **`db_default=`** (Django 5+) — the *database* supplies the value, so the old code's `INSERT`s, which do not name the column, still succeed. A Python `default=` does not help old code | — |
| **Add a NOT NULL column needing a computed backfill** | Add nullable; backfill in batches (below); add `CheckConstraint(… IS NOT NULL)` with `AddConstraintNotValid`, then `ValidateConstraint` | `SET NOT NULL` (Postgres uses the validated check and skips the table scan); drop the check |
| **Remove a column** | Stop using it in code; make it nullable or give it `db_default` if old code still writes it; remove it from **state only** (`SeparateDatabaseAndState`) | Drop the column — **a contract step** |
| **Rename a column** | Cheapest: rename the Python attribute only, keep `db_column="old_name"` — no DB change at all. Otherwise: add new, dual-write, backfill, switch reads | Drop the old column — contract |
| **Rename a model/table** | Keep `db_table` — rename in Python only | — |
| **Change a column's type** | Add a new column, dual-write, backfill | Switch reads, drop the old — contract |
| **Add an index to a populated table** | `AddIndexConcurrently` (`django.contrib.postgres.operations`) in a migration with `atomic = False` | — |
| **Add a unique constraint** | Build the unique index concurrently, then attach it (`ALTER TABLE … ADD CONSTRAINT … UNIQUE USING INDEX` via `RunSQL` with matching `state_operations`) | — |
| **Add a foreign key to a populated table** | `AddConstraintNotValid`, then `ValidateConstraint` in a separate migration; index built concurrently | — |
| **Remove a choice value** | Migrate the data off it first; keep the value accepted for a release | Remove the value — contract |

**Rules — the rest.**

- **Backfills are not schema migrations.** A data backfill over a real table runs in batches, each
  committed (`RunPython` in a migration with `atomic = False`, or a management command/job), and is
  idempotent. One transaction over a million rows holds its locks for the whole backfill.
- **Contract steps carry an explicit marker** and ship only after the expand release has been
  deployed everywhere that matters — for the core, that means after products have had a release to
  take it:

  ```python
  class Migration(migrations.Migration):
      contract = ContractStep(
          reason="Drop users.legacy_role; unread since the expand release.",
          expanded_in="2026.10.01",
      )
      operations = [migrations.RemoveField("user", "legacy_role")]
  ```

- **A contract migration in `core/` is a major version** of the platform ([`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md)).
- **`lock_timeout` during migrate.** Core overrides `migrate` (`core/management/commands/migrate.py`,
  subclassing Django's) to run `SET lock_timeout = '<MIGRATION_LOCK_TIMEOUT>'` on every connection
  it opens. An `ALTER TABLE` waiting for a lock queues every later query on that table **behind it**
  — one long-running transaction plus one migration is a full outage. With a timeout the migration
  fails fast and the deploy aborts at step 5, safely, before any new code runs.
- **Migrate connects directly to Postgres, never through a transaction pooler** (§ 12). Session
  settings such as `lock_timeout` do not survive statement-to-statement server reassignment, and
  some DDL cannot run through one. `MIGRATE_DATABASE_URL` (defaults to `DATABASE_URL`) exists for
  this.
- **The migrations doctor compares the database with the release before deploy** — applied
  migrations unknown to the release (database ahead of code), unapplied migrations, more than one
  leaf per app ([`OBSERVABILITY.md`](OBSERVABILITY.md) § 12, § 6 step 4 here).
- **Migrate from empty in CI**, on real Postgres, then `makemigrations --check --dry-run`, then seed.
  **And migrate from the previous release:** check out the last release tag, migrate a database
  containing fixture rows, check out `HEAD`, migrate again — the test that catches a data migration
  that only works on an empty table.
- **Never squash or rename a core or plugin migration once any product exists.** Products'
  migrations name core migrations in their `dependencies`; a squash in core breaks every product's
  graph on the next merge.
- **A migration never rewrites operator-authored content.** It may create, update or delete what the
  product ships and an operator cannot edit (seeded reference rows, system defaults — marked
  `is_system`). It never transforms rows a person wrote (templates, saved views, notification
  bodies), however safe the transform looks: a real near-miss was a regex migration that fixed every
  row in the one development database and would have mangled production templates. Corrections to
  authored content ship as a new default or an in-app "upgrade this template" action.

**Django + Next shape.** `core/migrations_policy.py` (`ContractStep`, the classifier),
`core/management/commands/migrate.py`, `manage.py doctor --only migrations`,
`MIGRATE_DATABASE_URL`, `MIGRATION_LOCK_TIMEOUT`.

**Enforced by.** `tests/architecture/test_migration_safety.py` — for every migration added since the
last release tag, classify each operation: **safe** (`CreateModel`, nullable or `db_default`
`AddField`, `AddIndexConcurrently`, `AddConstraintNotValid`, `ValidateConstraint`), **contract**
(`RemoveField`, `DeleteModel`, `RenameField`, `RenameModel`, `AlterField` to `null=False` without
`db_default`, type changes, `RunSQL` containing `DROP`), **locking** (`AddIndex` on an existing model,
`AddField` NOT NULL with only a Python default). Contract and locking operations fail unless the
migration carries `contract = ContractStep(…)` with both fields filled. Every `RunPython` must
declare `system_content_only = True` or carry a contract marker. The classifier has a fixture
migration per category as its positive controls. Plus `test_migrate_from_empty` and
`test_migrate_from_previous_release` in CI.

**Configurable, not hard-coded.** `MIGRATION_LOCK_TIMEOUT` (`5s`) · `MIGRATION_STATEMENT_TIMEOUT`
(unset — long DDL is allowed; waiting for a lock is not) · `MIGRATE_DATABASE_URL`.

---

## 9. Backups — **Tier 2 · Core**

**What.** `deploy/scripts/db-backup.sh <label>`, its verification, its off-box copy, its metrics
and its restore drill.

**Why.** A real incident: a test-gate script built a database URL with an **empty database name**;
libpq defaulted the name to the *user* name, which was the application database; the test fixture
ran `DROP SCHEMA public CASCADE` against the shared development database. The newest backup was
nineteen days old. Every line of the backup design below answers one way that story could have gone
differently.

**Rules.**

- **Labels with retention.** `hourly` (keep 48), `daily` (keep 30), `predeploy-*` and `manual-*`
  (**never pruned automatically** — a pre-deploy dump is the one you reach for after a bad deploy,
  and it is the one a naive prune deletes first).
- **Only the primary dumps.** `SELECT pg_is_in_recovery()` must be false; a replica exits 0 with a
  note.
- **`pg_dump -Fc` to `<name>.dump.partial`, then an atomic rename** after verification. A crash
  mid-dump never leaves a file that looks complete.
- **Verify before rename:** `pg_restore --list` must succeed, **and** the number of `TABLE DATA`
  entries must be ≥ the number of tables counted in the live database immediately before the dump.
  "The archive is readable" and "the archive contains the data" are different claims.
- **Record the state beside the dump** — `<name>.meta.json`: `APP_VERSION`, commit SHA, source
  `APP_ENV`, per-app migration leaf from `django_migrations`, table count, size, SHA-256. Restore
  (§ 10) reads it.
- **Off-box copy, verified.** Upload, then confirm the remote object's size (and checksum where the
  store supports it) equals the local file. Credentials go in a `0600` temporary config file, never
  on a command line (visible in `ps`); the script **refuses to read an env file that is group- or
  world-readable**.
- **Strict permissions:** `umask 077`; backup directory `0700`; files `0600`.
- **Distinct exit codes** so callers can decide: `0` ok · `2` configuration · `3` dump failed ·
  `4` verification failed · `5` off-box copy failed · `6` prune failed. For a `predeploy-*` label, an
  off-box failure (`5`) is reported loudly but the deploy may proceed — the local dump is verified
  and is the one the deploy needs.
- **Freshness is a metric, and its absence alerts.** The script writes node-exporter textfile
  metrics — `app_backup_last_success_timestamp_seconds{label}`, `app_backup_size_bytes{label}`,
  `app_backup_offbox_last_success_timestamp_seconds{label}` — and the rule pack alerts on
  **stale-or-absent** ([`OBSERVABILITY.md`](OBSERVABILITY.md) § 9).
- **Media and object storage** are backed up by their own mechanism (a tarball of `MEDIA_ROOT` in
  filesystem mode; bucket versioning in object-store mode), labelled and verified the same way.
- **A backup you have never restored is a hypothesis.** A monthly `db-restore.sh --verify-only`
  restores the latest daily dump into a scratch database, runs `migrate --check` and compares
  per-table row estimates with the metadata, then drops the scratch database. Its result is a
  metric too.

**Django + Next shape.** `deploy/scripts/{db-backup,db-backup-verify,db-backup-offbox,
db-restore}.sh`, `deploy/cron/backup.cron` (or job-registry entries when the scheduler runs on the
database host), textfile collector directory `NODE_EXPORTER_TEXTFILE_DIR`.

**Enforced by.** `tests/infra/test_backup_script.py` against a throwaway Postgres service in CI:
`test_partial_never_renamed_on_verify_failure` · `test_predeploy_never_pruned` ·
`test_refuses_world_readable_env` · `test_exit_codes` (each failure injected) ·
`test_meta_records_migration_state` · plus `shellcheck` and `test_uses_umask_077`.

**Configurable, not hard-coded.** `BACKUP_DIR` · `BACKUP_RETAIN_HOURLY` (48) ·
`BACKUP_RETAIN_DAILY` (30) · `BACKUP_OFFBOX_URL` · `BACKUP_OFFBOX_CREDENTIALS_FILE` ·
`BACKUP_STALE_HOURS` (26, used by the rule pack).

---

## 10. Restore — **Tier 2 · Core**

**What.** `deploy/scripts/db-restore.sh <dump> [--keep-config] [--sanitise] [--migrate]`, the
`config_snapshot` commands and the `post_restore` event that make a restore safe — in particular a
restore of **another environment's** data. The settings-level semantics of what "keep config" means
are [`CONFIGURATION.md`](CONFIGURATION.md)'s; this is the procedure and the registry.

**Why.** A real incident: environments shared one encryption key, and a production dump loaded into
staging carried **working** credentials to production's object store, chat workspace, billing
system and network proxies — with Celery running, so staging's scheduler started acting on
production's integrations within a minute. Separately, a restored install's SSO sign-in broke with
"access blocked", because the restored SSO client configuration carried the *source* host's
redirect URIs.

**Rules — the procedure.**

1. **Read the dump's table of contents first** (`pg_restore --list`). If the archive is unreadable,
   stop — **the target database has not been touched**.
2. **Show identity and refuse the dangerous combinations:** target environment and database; the
   dump's `meta.json` (source environment, version, date). A production-sourced dump into a
   non-production target requires `--sanitise` (§ 1).
3. **Stop the application containers** — web, workers and **beat** above all.
4. **`manage.py config_snapshot dump`** of the target, **before** anything is dropped (default on
   for cross-environment restores; `--keep-config` explicitly for same-environment).
5. **Drop and recreate the database** — not `pg_restore --clean`, which cannot drop objects other
   objects reference and leaves a half-restored database when it gives up.
6. `pg_restore --exit-on-error --no-owner --role=<app role> -j <n>`.
7. **Compare migration state.** `migrate --check`: unapplied migrations (the dump is older than the
   code) are printed and migration is **offered**, never silent — even under `--yes` it needs
   `--migrate`. Applied migrations the code does not know (the dump is newer): stop and say which
   version to deploy.
8. **`manage.py config_snapshot load`**, then `sanitise_snapshot` if `--sanitise`.
9. **`manage.py post_restore`** publishes `core.restore_completed` on the event bus
   ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)): handlers drop artefacts keyed to rows that may no longer
   exist — the application cache namespace, search indexes (marked for reindex), derived file
   caches. Handlers are idempotent; a failing handler is a warning, and the command's exit code
   reflects it.
10. **Start the application and verify** as § 6 does.

**Rules — `config_snapshot`.** What each kind of install configuration does on restore —
`singleton`, `setting`, `scoped`, `schedule`, `credential`, declared through
`registry.install_config.register(Model, kind=…)` — and the environment stamp that warns when a
database was last written by a different environment, are specified in
[`CONFIGURATION.md`](CONFIGURATION.md) § 17. Three operational rules sit on top:

- **Snapshot before drop, load after migrate** — steps 4 and 8 above, in that order, every time. A
  snapshot taken after the drop is a snapshot of nothing.
- **Beat stays stopped until `config_snapshot load` has run.** Between the restore and the load, the
  database holds the *source's* enabled schedules; a scheduler started in that window acts on them.
- **Completeness is a doctor finding.** A model holding encrypted fields, or a scheduler row type,
  that is not registered with `install_config` is reported by the `settings` doctor
  ([`OBSERVABILITY.md`](OBSERVABILITY.md) § 12) — derived from the models, not from a list.

**Enforced by.** `test_config_snapshot.py` (owned by [`CONFIGURATION.md`](CONFIGURATION.md) § 17) ·
`test_post_restore.py` (handler failure → warning, non-zero exit, other handlers still
run) · `test_restore_script.py` (unreadable dump → target untouched; `--clean` never used;
production-into-staging without `--sanitise` refused; unapplied migrations not applied without
`--migrate`).

**Configurable, not hard-coded.** Install-config kinds are registry entries; the restore flags are
explicit per run by design.

---

## 11. The test-database guard — **Tier 1 · Core**

**What.** A guard in `backend/conftest.py` that refuses to start a test session against any database
that is not unambiguously a test database. Lands with [`BUILD_ORDER.md`](../planning/BUILD_ORDER.md)
**2.1**.

**Why.** The incident in § 9. `pytest-django`'s `test_` prefix is good protection by default and is
defeated by exactly the configurations that appear in practice: a custom `TEST["NAME"]`,
`--reuse-db`/`--keepdb`, a `DATABASE_URL` with the name in the query string, an empty name that libpq
fills with the user name.

**Rules.**

- **Resolve the name the run will actually use:** `DATABASES[alias]["TEST"]["NAME"]` or
  `test_<NAME>`, with the xdist `_gwN` suffix, after parsing `DATABASE_URL` **including**
  query-string `dbname=` overrides and percent-encoding.
- **Refuse** (fail the session before any fixture runs) when: the resolved name is empty; it does
  not start with `test_`; it equals the non-test `NAME`; the host is not in
  `TEST_DB_ALLOWED_HOSTS` (local and CI service names) — a test run against a shared or staging host
  is refused even with a correct-looking name.
- **The guard has its own tests,** one per bypass above, each asserting refusal.
- **Hermetic tests** (per-test in-memory cache, in-memory storage, `locmem` email — so tests never
  touch a developer's live cache or bucket) are [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md)'s;
  this guard is the one that protects data.

**Enforced by.** `tests/harness/test_db_guard.py`.

**Configurable, not hard-coded.** `TEST_DB_ALLOWED_HOSTS` (default `localhost,127.0.0.1,db,postgres`).

---

## 12. Connection pooling and Postgres — **Tier 2 · Core**

**What.** One database settings factory used by every process, three explicit pooling modes, the
rules each mode imposes on application code, a connection budget, and the Postgres server settings a
product runs with.

**Why.** A transaction-mode pooler breaks session-level features **silently**: a session advisory
lock acquired on one server connection is released on another; a prepared statement exists on a
server connection the next query never reaches; a server-side cursor outlives its transaction. And
a duplicated per-process database setup in workers leaked connections until the pooler was
exhausted and the web tier could not connect.

**Rules — one factory.**

- `core/db.py::database_config(env) -> dict` builds `DATABASES` for web, Celery and management
  commands alike. **No process-specific database settings** — a worker that configures its own
  connection is how the leak above happened.
- `OPTIONS["application_name"]` is set per process role (`app-web`, `app-worker`, `app-beat`,
  `app-migrate`) so `pg_stat_activity` attributes every connection.
- `OPTIONS["connect_timeout"]` is always set (default 5).

**Rules — the three modes (`DB_POOL_MODE`).**

| Mode | Settings | Constraints on code |
|---|---|---|
| `direct` | `CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True` | None beyond the budget |
| `native` (Django 5.1+ psycopg pool) | `OPTIONS["pool"]={min_size, max_size, timeout}`, **`CONN_MAX_AGE=0`** | **Never behind PgBouncer** — two pools, neither aware of the other |
| `pgbouncer` (transaction mode) | **`CONN_MAX_AGE=0`**, **`DISABLE_SERVER_SIDE_CURSORS=True`** (`.iterator()` otherwise opens a cursor that outlives its transaction), psycopg `OPTIONS["prepare_threshold"]=None` | **Only `pg_advisory_xact_lock`**, never session advisory locks; `SET LOCAL`, never `SET`; no `LISTEN`/`NOTIFY`, no temp tables or `WITH HOLD` cursors across transactions; never hold a transaction open across slow I/O |

- **Migrate bypasses the pooler** (`MIGRATE_DATABASE_URL`, § 8).
- **A system check** `dbx.E011` asserts the settings above match the declared mode.
- **A code check** fails on `pg_advisory_lock(` / `pg_try_advisory_lock(` (non-`xact`) anywhere in
  the tree — the lock helper in [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) is the only
  sanctioned way to take a database lock.

**Rules — the connection budget.** The `connections` doctor computes and checks:

```
clients = web_instances × GUNICORN_WORKERS × GUNICORN_THREADS
        + Σ worker_services × concurrency
        + beat + cron/management + migrate (1) + monitoring + headroom
direct / native:  clients (× pool max_size for native) ≤ max_connections − superuser_reserved − admin headroom
pgbouncer:        clients ≤ max_client_conn,  and  default_pool_size × (db, user) pairs + reserve_pool
                  ≤ max_connections − superuser_reserved − admin headroom
```

Written down because a deploy that adds a worker service is otherwise the deploy that exhausts the
database.

**Rules — Postgres server settings** (in the development compose too, § 1):

`idle_in_transaction_session_timeout = 60s` (a forgotten transaction holds locks and blocks vacuum
and migrations) · `pg_stat_statements` in `shared_preload_libraries` · `log_min_duration_statement =
500ms` · `log_lock_waits = on` with `deadlock_timeout = 1s` · a per-role `statement_timeout` for the
application role (the § 7 ladder), none for the migrate role · `password_encryption =
scram-sha-256`.

**Enforced by.** `dbx.E011` · `test_no_session_advisory_locks` (grep, positive control) ·
`test_one_database_factory` (Celery app imports settings, never builds its own) · the `connections`
doctor · the policy test that the compose Postgres service carries the settings above.

**Configurable, not hard-coded.** `DB_POOL_MODE` · `DB_CONN_MAX_AGE` · `DB_POOL_MIN_SIZE` /
`DB_POOL_MAX_SIZE` · `DB_CONNECT_TIMEOUT` · `DB_STATEMENT_TIMEOUT` · `MIGRATE_DATABASE_URL`.

---

## 13. A separate database for high-volume append-only logs — **Tier 2 · Core** (off by default)

**What.** An optional second database alias, `logs`, for append-only, high-volume, low-value-per-row
tables — email delivery logs, webhook delivery logs, API request logs, error occurrences — with a
router and a fallback to `default` when it is not configured.

**Why.** Those tables grow fastest **exactly when something is wrong** (a retry storm, an attack),
compete with business queries for the pooler's server connections, bloat the main database's WAL,
backups and restore time, and have a different retention policy. Moving them is cheap if the seam
exists from the start and expensive once a hundred queries join against them.

**Rules.**

- `DATABASES["logs"]` from `LOGS_DATABASE_URL`; **absent → the router sends everything to
  `default`** and the product runs unchanged. Tests run in both configurations.
- **Models opt in by registration**, `registry.log_models.register(EmailDelivery)`; the router
  (`core.db.routers.LogsRouter`) routes reads, writes and `allow_migrate` for exactly those models.
- **No foreign keys from a log model to a main-database model** — Django cannot enforce them across
  databases. Store the id and a denormalised label (`recipient_id`, `recipient_label`).
- **Writes are best-effort and never break the business transaction:** written from
  `transaction.on_commit()`, on the `logs` connection; a failure increments
  `app_log_db_write_failed_total{model}` and logs a warning.
- **Its own connection settings** (direct, small pool), **its own backup schedule and retention**
  (the retention engine runs per alias, [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)).

**Enforced by.** `test_logs_router.py` (configured: rows land on `logs`; unconfigured: on
`default`; a registered model with a FK to a main model fails a check) · `dbx.W004` when a registered
log model has a foreign key.

**Configurable, not hard-coded.** `LOGS_DATABASE_URL` · membership is a registry.

---

## 14. The reverse proxy — **Tier 2 · Core**

**What.** A reference nginx configuration in `deploy/nginx/` — the edge in front of Django and Next
— and the rules any proxy a product uses must satisfy, because
[`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) Ch. 17 and [`OBSERVABILITY.md`](OBSERVABILITY.md) § 1
depend on them.

**Why.** Each rule below corresponds to a way a correct application was made incorrect by its proxy:
a client-supplied `X-Forwarded-For` that defeated every rate limit; a config reload that re-read a
stale file for weeks; a single client holding every upload slot; hostnames split across two origins
so the frontend's route guard could never see the session.

**Rules.**

- **Set, never append, the forwarding headers.** `proxy_set_header X-Forwarded-For $remote_addr;`
  (not `$proxy_add_x_forwarded_for`), so `TRUSTED_PROXY_COUNT=1` counts exactly the hop that
  observed the client. Behind a load balancer or CDN, the edge first restores the real client with
  `set_real_ip_from <trusted CIDRs>` + `real_ip_header`, then sets the header — and
  `TRUSTED_PROXY_COUNT` counts every trusted hop.
- **`X-Forwarded-Proto $scheme`, set.** `SECURE_PROXY_SSL_HEADER` is only trustworthy when the proxy
  overwrites that header on every request.
- **`X-Request-ID $request_id`, set** ([`OBSERVABILITY.md`](OBSERVABILITY.md) § 1) — or, behind a
  trusted upstream that already sets one, passed through after the same validation.
- **One origin.** Recommended topology: one hostname; `/api/` (and `/admin/` when enabled) to Django,
  static to the proxy, everything else to Next. Cookie authentication requires same-*site*
  ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.1); a Next route guard that reads the session marker
  requires the cookie to be visible to page requests, which in practice means same-*origin*. Split
  hostnames bounce every signed-in user back to sign-in, and nothing logs why.
- **Location order:** API and admin prefixes before `/`. In any first-match router, a catch-all
  listed first swallows the API.
- **Private files are never served from a path.** User uploads go through an authenticated view
  answering `X-Accel-Redirect` to an `internal` location. A public `location /media/ { alias …; }`
  makes every uploaded document public, whatever the storage backend setting says.
- **Configuration is mounted as a directory,** `./deploy/nginx/conf.d:/etc/nginx/conf.d:ro` — never
  a single-file bind mount. A `git pull` replaces a file by writing a new inode; a single-file mount
  stays pinned to the old one, and `nginx -s reload` keeps re-reading the stale config. (If a
  single-file mount is unavoidable, the driver must restart — not reload — and assert the container's
  inode equals the host file's.)
- **Per-request DNS for upstreams:** `resolver 127.0.0.11 valid=5s ipv6=off;` and a variable in
  `proxy_pass` (`set $api http://web:8000; proxy_pass $api;`) so a replaced container's address is
  learnt within seconds. With a variable, nginx passes the request URI unchanged — do not rely on
  prefix stripping. (nginx ≥ 1.27.3 also supports `server web:8000 resolve;` inside an `upstream`
  block; either satisfies the rule.)
- **Retries:** `proxy_next_upstream error timeout http_502 http_503;` with
  `proxy_next_upstream_tries 2`; **never `non_idempotent`** (§ 7).
- **Body limits:** a modest global `client_max_body_size`; **`4k` on the login and other
  credential endpoints** (a credential is small; a large body there is an attack or a bug); larger
  limits only on the upload locations, sized from the upload-purpose registry
  ([`API_PLATFORM.md`](API_PLATFORM.md)).
- **Upload connection zones, two of them:** `limit_conn_zone $server_name zone=uploads_global` caps
  total concurrent uploads (and therefore spool disk: slots × body limit) and
  `limit_conn_zone $binary_remote_addr zone=uploads_per_ip` stops one client taking every slot.
  `client_body_temp_path` on a volume whose size is known.
- **`server_tokens off`.**
- **A timing log format, as JSON:** `request_id`, status, bytes, `request_time`,
  `upstream_response_time`, `upstream_connect_time`, `upstream_addr` — the access log is where
  per-request lines belong ([`OBSERVABILITY.md`](OBSERVABILITY.md) § 2).
- **Health locations:** `/api/health/live/` (and its alias `/api/health/`) and `/api/health/ready/`
  exempt from edge rate limits; every
  health location has a ready sibling.
- **`/metrics` returns 404 at the edge;** monitoring UIs (metrics, dashboards, mail catcher, task
  monitors) bind to loopback and are reached through an SSH tunnel.
- **Compression and BREACH:** compressing JSON is acceptable because the CSRF token travels in a
  header and a cookie, never in a response body that also reflects attacker-controlled input — keep
  it that way, and write the reason next to the `gzip` directive.

**Enforced by.** § 16: `test_forwarded_headers_are_set_not_appended`,
`test_nginx_config_mounted_as_directory`, `test_login_body_limit`,
`test_health_location_has_ready_sibling`, `test_metrics_not_public`, `test_no_non_idempotent_retry`,
`test_no_public_media_alias`; `nginx -t` on the reference config in CI.

**Configurable, not hard-coded.** Hostnames, certificate paths, trusted CIDRs, body limits and
upload-zone sizes are template variables in `deploy/nginx/values.env`; the rules are the template.

---

## 15. Container hygiene — **Tier 1 · Core**

**What.** The defaults every service in every compose file carries, and the per-role healthchecks.
Lands with [`BUILD_ORDER.md`](../planning/BUILD_ORDER.md) **4.4**.

**Why.** A real incident: the cache/broker was published to the internet without authentication,
was found by a scanner, was made an attacker's replica, and background processing was down for
about ten hours. Every rule below is cheap on day one and a project on day three hundred.

**Rules.**

- **Only the edge proxy publishes ports.** Everything else is unpublished (`expose` only) or bound to
  `127.0.0.1:` in development. Production compose resets inherited publishes (`ports: !reset []`).
- **Every secret is `${VAR:?}`** — compose refuses to start without it — never `${VAR:-default}`.
  **`.env.example` ships secrets blank**, so a copied file cannot boot on a placeholder.
- **`security_opt: [no-new-privileges:true]` and `cap_drop: [ALL]`** on every application service;
  the database gets only the capabilities it needs back (`cap_add`, each with a comment).
- **Non-root** numeric uid in every application image; `read_only: true` root filesystem with
  `tmpfs` for `/tmp` where the service tolerates it.
- **Resource limits** (`mem_limit`, `cpus`, `pids_limit`) on every production service — one runaway
  worker must not take the host.
- **A log driver that survives recreation**, set once through an `x-logging` anchor: `journald`
  (rotation and caps configured on the host, recorded in git) or a shipper. `json-file` is deleted
  with the container, so every deploy erases the logs of the release it replaced.
- **A healthcheck on every long-running service:** web → readiness; worker →
  `celery -A config inspect ping -d celery@$HOSTNAME -t 10`; beat → a process check (beat has no
  endpoint; its real health is the staleness probe in [`OBSERVABILITY.md`](OBSERVABILITY.md) § 6 —
  an inherited HTTP healthcheck on beat always fails); frontend → a trivial route handler; database
  → `pg_isready`; cache → an authenticated `PING`.
- **`stop_grace_period`** ≥ the service's graceful timeout (web: gunicorn's; worker: the longest
  soft time limit).
- **Broker and cache are different eviction policies.** The broker needs `--appendonly yes
  --maxmemory-policy noeviction` (a queue must survive a restart and must never lose a message to
  eviction); a cache wants `allkeys-lru`. Two Redis instances (or two logical services), not one with
  a compromise — a cache filling a `noeviction` instance makes the broker refuse writes.
- **Redis requires authentication** (ACL user or `requirepass` from a secret file), even on an
  internal network.
- **Named volumes** for stateful data (§ 2).
- **Pinned versions** for every third-party image, by digest in production.

**Enforced by.** § 16.

**Configurable, not hard-coded.** Limits and versions are compose variables with defaults in
`deploy/compose/values.env`.

---

## 16. Infrastructure policy-as-tests — **Tier 1 · Core**

**What.** `backend/tests/infra/` — pytest modules that parse the compose files, Dockerfiles, proxy
configuration, alert configuration and shell scripts, and fail when a policy in this document is
broken. They run in CI with everything else.

**Why.** Infrastructure files are the least-reviewed code in a repository and the most dangerous.
The exposed-broker incident in § 15 was a one-line change to a compose file that no test read.

**Rules.**

- **Parse, don't grep, where a parser exists:** compose via `docker compose config --format json`
  (resolved, all overlays merged — the file an operator reads is not the file Docker runs), YAML for
  alert configs, a small Dockerfile instruction parser, `nginx -t` plus a normalised-text reader for
  proxy config, `bash -n` and `shellcheck` for scripts.
- **Enumerate from the files; fail on an empty universe.** A policy that finds zero services is
  looking in the wrong place.
- **Every rule has a positive control:** a fixture that violates it, asserting the test catches it.

| Test | Asserts |
|---|---|
| `test_only_edge_publishes_ports` | No service but the edge publishes a port on a non-loopback address |
| `test_secrets_use_required_interpolation` | Every variable whose name matches the secret pattern is `${X:?}` |
| `test_env_example_secrets_blank` | Every secret key in every `*.env.example` is empty |
| `test_every_service_has_log_driver` | The `x-logging` anchor is applied to every service; no `json-file` in production |
| `test_every_long_running_service_has_healthcheck` | … and web's targets readiness |
| `test_app_images_non_root` / `test_base_images_pinned` | Final-stage `USER` is numeric non-root; production `FROM` lines carry a digest |
| `test_prod_images_versioned` | No `build:`, no `:latest`, image tag is `${APP_VERSION:?}` |
| `test_no_source_mounts_or_reload_in_prod` | No bind mount of the source tree; no `--reload`, `runserver`, `next dev` |
| `test_no_new_privileges_and_cap_drop` / `test_resource_limits` | Present on every application service |
| `test_every_queue_has_a_worker` | Every queue in the job registry / `CELERY_TASK_ROUTES` is consumed by some worker service's `-Q` |
| `test_broker_noeviction` | The broker service runs `noeviction` with append-only |
| `test_nginx_*` | § 14's list |
| `test_alertmanager_*` | [`OBSERVABILITY.md`](OBSERVABILITY.md) § 9's list |
| `test_deploy_driver_*` / `test_backup_script_*` | §§ 6 and 9 |
| `test_env_parity` | § 1 |

**Enforced by.** The suite itself, in CI, blocking.

---

## 17. The Next.js production build — **Tier 2 · Core**

**What.** The order and the checks for building the frontend for production.

**Why.** Five failures that each reported success. A build against an empty database cached empty
responses in Next's persistent fetch cache, a later build **replayed** them, `generateStaticParams`
returned nothing, and every dynamic page 404'd on a build that finished green — the tell was a
sitemap listing URLs that 404. An assertion that the API origin was baked in used `grep -ql … | wc -l`,
which always prints `0` (`-q` prints nothing), so it could only ever pass. `INTERNAL_API_URL` and
`NEXT_PUBLIC_API_URL` swapped: saves succeeded, nothing ever appeared.

**Rules.**

- **Prefer a build that needs no API.** Pages that render data render it at request time; then the
  frontend build is independent of the backend and these ordering rules never bite.
- **If any page prerenders from data, the order is mandatory:** migrate → seed → start the API →
  wait on `/api/health/ready/` → build the frontend. CI does the same, against a real seeded API.
- **Clear the persistent fetch cache before a production build:** `rm -rf .next/cache/fetch-cache`.
  The rest of `.next/cache` (compiler caches) may be kept for speed.
- **`NEXT_PUBLIC_*` is baked at build. Assert it with a check that can fail:**
  `test "$(grep -rl -- "$EXPECTED_API_ORIGIN" .next/static | wc -l)" -gt 0` — and the negative:
  `! grep -rq -- "localhost:" .next/static` for a production build. Each with a positive-control run
  in the check's own test.
- **`INTERNAL_API_URL` (server-side, container network) vs `NEXT_PUBLIC_API_URL` (browser).**
  Server components and route handlers use the first; the browser bundle only ever sees the second.
  Swapped, both fail silently — the rule and the lint check that enforces the split live in
  [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md).
- **Never build in the development container** ([`AGENTS.md`](../../AGENTS.md) § 2) — `.next/` is
  shared with the running dev server. Production builds happen in the release image build (§ 5) on a
  clean checkout.
- **`output: "standalone"`, `deploymentId = APP_VERSION`, `poweredByHeader: false`.**

**Enforced by.** `frontend/scripts/verify-build.sh` (the greps above, with its own test), run in CI
after `next build` and in `scripts/release/build.sh`.

**Configurable, not hard-coded.** `NEXT_PUBLIC_API_URL` · `INTERNAL_API_URL` ·
`EXPECTED_API_ORIGIN` (defaults to the origin of `NEXT_PUBLIC_API_URL`).

---

## 18. Shared development environments — **Process**

**What.** Etiquette for a development or staging box more than one person uses.

**Why.** A branch tested on a shared box and then abandoned leaves the next person with a schema
their code does not know, workers that cached a task list naming tasks that no longer exist (the
queue fills with "Received unregistered task"), and a beat schedule from a branch nobody is on.

**Rules.**

- **Leave it as you found it:** the same branch; the same migration state — before switching back,
  `migrate <app> <leaf-on-base-branch>` for every app your branch added migrations to; no stray
  schema objects.
- **Restart workers and beat after any switch.** They cache the task registry and the schedule;
  restoring the code is not enough.
- **`docker compose cp` into a bind-mounted container writes through to the host tree** — i.e. into
  the shared checkout.
- **Tooling beats memory:** `scripts/dev/branch_state.sh --save` records branch and per-app
  migration leaves to a file; `--restore` puts them back and restarts workers and beat.

**Enforced by.** The helper script and the `migrations` doctor, which flags a database ahead of the
checked-out code.

---

## 19. Release git flow and versioning — **Process** (an option for products)

**What.** A branch-and-tag flow for products that run a staging environment, and what version
numbers mean for a platform. [`AGENTS.md`](../../AGENTS.md) fixes the default branch as `main`; this
is an additional flow a product may adopt, not a change to that rule. Details of semver and the
changelog live in [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md).

**Why.** Squash-merging `staging` into `main` diverges their histories, after which "what is on
production" is no longer a git question. And a deploy without a tag has no rollback target.

**Rules.**

- **`main` is always an ancestor of `staging`.** CI on `main` asserts
  `git merge-base --is-ancestor origin/main origin/staging`.
- **Feature branches are cut from `staging`** and squash-merged into it by PR.
- **`staging → main` is `git merge --ff-only`** — never a squash, never a merge commit.
- **Hotfixes branch from `main`** and are back-merged into `staging` **with a merge commit**, never a
  squash, so the ancestry invariant survives.
- **Every production deploy is an annotated tag** — CalVer `vYYYY.MM.DD[.N]` for products (a product
  release is a point in time), SemVer `vMAJOR.MINOR.PATCH` for the core (a core release is a
  compatibility promise). The tag is the rollback target (§ 6).
- **SemVer for a platform:** **major** — taking the update needs work (a seam changed shape, a
  config key moved, a contract migration, § 8); **minor** — new capability, merge freely;
  **patch** — a fix or hardening, take promptly.
- **Core migrations are never squashed or renamed** after the first product exists (§ 8).

**Enforced by.** The ancestry CI check; `scripts/release/build.sh` refusing anything that is not an
exact annotated tag (§ 5).

---

## 20. Settings

Script-level keys live in the environment's `.env`; Django keys come from `.env` via
`django-environ`. Every key goes into the matching `.env.example` in the same change — secrets blank.

| Key | Default | Section |
|---|---|---|
| `APP_ENV` / `APP_SLUG` / `COMPOSE_PROJECT_NAME` | — / from directory / derived | § 1 ([`CONFIGURATION.md`](CONFIGURATION.md) owns `APP_ENV`) |
| `WEB_PORT` / `API_PORT` / `DB_PORT` | chosen and persisted by setup | § 2 |
| `DBX_WITH_MAILCATCHER` / `DBX_WITH_OBJECTSTORE` | `0` | § 2 |
| `SETUP_WIZARD_ENABLED` / `SETUP_TOKEN` / `SETUP_TOKEN_PATH` | `True` / generated / data volume | § 3 |
| `DEV_SIGNIN_HINT_ENABLED` | `True` in development | § 4 |
| `IMAGE_PREFIX` / `APP_VERSION` | — / `0.0.0-dev` | § 5 |
| `DEPLOY_HOST` / `DEPLOY_LOG_DIR` / `ROLLOUT_HEALTH_TRIES` / `ROLLOUT_HEALTH_INTERVAL` | — / — / `60` / `2` | § 6 |
| `VERIFY_LOG_PATTERNS` / `VERIFY_CLOSED_PORTS` | core list / DB, cache, broker, metrics | § 6 |
| `GUNICORN_WORKERS` / `_THREADS` / `_TIMEOUT` / `_GRACEFUL_TIMEOUT` / `_MAX_REQUESTS` / `_MAX_REQUESTS_JITTER` | `2` / `1` / `30` / `30` / `1000` / `100` | § 7 |
| `MIGRATE_DATABASE_URL` / `MIGRATION_LOCK_TIMEOUT` / `MIGRATION_STATEMENT_TIMEOUT` | `DATABASE_URL` / `5s` / unset | § 8 |
| `BACKUP_DIR` / `BACKUP_RETAIN_HOURLY` / `BACKUP_RETAIN_DAILY` / `BACKUP_OFFBOX_URL` / `BACKUP_OFFBOX_CREDENTIALS_FILE` / `BACKUP_STALE_HOURS` | — / `48` / `30` / — / — / `26` | § 9 |
| `TEST_DB_ALLOWED_HOSTS` | `localhost,127.0.0.1,db,postgres` | § 11 |
| `DB_POOL_MODE` / `DB_CONN_MAX_AGE` / `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` / `DB_CONNECT_TIMEOUT` / `DB_STATEMENT_TIMEOUT` | `direct` / `60` / `2` / `10` / `5` / `25s` | § 12 |
| `LOGS_DATABASE_URL` | empty (off) | § 13 |
| `INTERNAL_API_URL` / `NEXT_PUBLIC_API_URL` / `EXPECTED_API_ORIGIN` | — / — / derived | § 17 |

**Registries this file adds** (each must appear in [`EXTENSIBILITY.md`](EXTENSIBILITY.md)'s
catalogue): `sanitisers` · `log_models` · `setup_steps`. It also depends on `install_config`, which
[`CONFIGURATION.md`](CONFIGURATION.md) § 17 owns.

**New system checks:** `dbx.E011` (pool-mode settings consistent) · `dbx.W004` (log model with a
foreign key).

---

## 21. ⚠️ Conflicts with existing docs

| # | Where | What is wrong | Fix |
|---|---|---|---|
| 1 | [`../NEW_PROJECT.md`](../NEW_PROJECT.md) § 1 and [`../planning/CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 7 | Generate `SECRET_KEY` with Django's `get_random_secret_key()`. Its alphabet includes `$ # % ( ) &`. **django-environ treats a value beginning with `$` as a reference to another variable** (verified in the installed `environ.py`: a leading `$` is stripped and the remainder looked up), so about one key in fifty silently resolves to something else or fails to boot; docker compose also interpolates `$` in `.env` values | Generate with `secrets.token_urlsafe(50)` (or setup's `manage.py generate_secret`, § 2); hex for database passwords |
| 2 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.4 ("`dbx.E005` refuses to boot") and [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-17** | Django system checks run for `manage.py` commands and `runserver`, **not** when gunicorn serves the app. As written, `dbx.E005` never runs in a production process | Keep `dbx.E005` as a check, and make it bite in two places that do run: the import-time boot audit ([`CONFIGURATION.md`](CONFIGURATION.md)) and the deploy driver's validate step (`check --deploy --fail-level WARNING` inside the new image, § 6). Reword "refuses to boot" to say which of these enforces it |
| 3 | [`DEPLOYMENT.md`](DEPLOYMENT.md) § 2, backend | `uv sync --frozen` installs the dev group into production; `migrate` and `collectstatic` are listed as deploy-time steps on the server | Runtime images use `uv sync --frozen --no-dev`; `collectstatic` runs at image build; `migrate` is a separate driver step from the **new** image before any swap, never in an entrypoint (§§ 5, 6) |
| 4 | [`DEPLOYMENT.md`](DEPLOYMENT.md) § 2, frontend | `npm ci && npm run build && npm run start` on the deploy target | The frontend is built once, in the release image, on a clean checkout (§§ 5, 17); the server only pulls it. The build order and fetch-cache rule of § 17 apply |
| 5 | [`DEPLOYMENT.md`](DEPLOYMENT.md) § 2, "Both" | Says `NEXT_PUBLIC_API_URL` is baked at build — correct — but gives no way to check it | Add the § 17 assertion; note that `grep -ql … \| wc -l` cannot fail |
| 6 | [`DEPLOYMENT.md`](DEPLOYMENT.md) § 3 | Health table (see [`OBSERVABILITY.md`](OBSERVABILITY.md) § 16 #2) | Three rungs; container healthchecks on readiness |
| 7 | [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md) § "Adding a non-nullable field" | Prescribes three migrations and three deploys for every NOT NULL addition. Since Django 5.0, `db_default=` makes a constant-default NOT NULL column safe for old code in **one** migration; the three-step pattern is still right for computed backfills — and its step 3 should validate a `NOT VALID` check first to avoid a full-table scan under lock | Add the `db_default` case and the `AddConstraintNotValid` → `ValidateConstraint` → `SET NOT NULL` sequence; link § 8 for the full expand/contract table |
| 8 | [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md) § "Merge conflicts in migrations" | Correct for development; says nothing about a database **ahead** of the code at deploy time (a branch deployed to a shared box) | Link the migrations doctor (§ 8) and § 18 |
| 9 | [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md) **4.1** | "Rename, fresh `SECRET_KEY`, write env files, migrate, seed, print the URL" omits port selection and persistence, fill-only-empty secrets, readiness waits and the final health poll — each a known first-run failure | Extend the acceptance criteria with § 2's flow; keep "idempotent and safe to re-run" |

---

## Pending decisions (for the repository owner)

1. **Wizard or CLI-only first run for the core?** § 3 recommends shipping the wizard in core
   (Tier 2) with `SETUP_WIZARD_ENABLED`; the alternative is `bootstrap_admin` only, with the wizard
   as a Tier 3 module.
2. **Default pooling mode.** `direct` is the recommendation until a product measures connection
   pressure; `native` is the next step; `pgbouncer` only when many processes share one database.
3. **Migration linter:** the small custom classifier in § 8 (knows `ContractStep`, ~150 lines) or
   `django-migration-linter` configured to honour the marker. Recommendation: custom — the marker and
   the release-tag diff are the valuable parts.
4. **Log database alias (§ 13):** ship the seam in core now (recommended — the router is small and
   retrofitting is not), or defer until a product needs it.
5. **Release git flow (§ 19):** adopt `staging`/`main` with ff-only releases as the recommended
   product flow, or leave products on trunk-based `main` with tags.
6. **Where backups run:** host cron on the database host (simplest; the § 9 script) or a job in the
   application scheduler (visible in the run monitor, but the scheduler then depends on the thing it
   backs up). Recommendation: host cron, with freshness watched by metrics either way.

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
