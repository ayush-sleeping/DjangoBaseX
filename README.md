<div id="top"></div>

## 🚀 &nbsp; DjangoBaseX
> A Django 5 + Next.js Full Stack Starter Boilerplate.

A secure, modular, production-ready base project using **Django 5 + Django REST Framework** for the API and **Next.js (App Router)** for the frontend — ideal for building scalable web applications with a Python backend and a TypeScript frontend.

> **Status:** checked 2026-11-14 · a platform with auth, RBAC, a Users module, plugins, jobs and an app shell built; phases 0–8 of the build order are done except 7.7–7.8 and 8.5b. The two halves run and talk to each other, and the **conventions, decisions and build order are fully documented** — see [`documentation/INDEX.md`](documentation/INDEX.md). Features are added module-by-module following [`BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md).
>
> **Not deployable yet.** Auth, RBAC, the Users module with invitations, plugins and a pytest + Vitest suite with CI are built; there is no production Docker (a development Compose stack exists) and no deployment topology. That list is honest and tracked — see [Project Status](#project-status) and [`documentation/planning/TECH_DEBT.md`](documentation/planning/TECH_DEBT.md).

## Overview

**What DjangoBaseX Is**

A starter kit for developers who want to skip repetitive setup work and start building features right away.
- **Django 5 backend** → clean REST API architecture (DRF), OpenAPI docs, env-driven settings.
- **Next.js frontend** → App Router, TypeScript, Tailwind CSS, typed API client.
- **Security baked in** → CORS, CSRF, rate limiting (DRF throttling), secrets from `.env`.
- **Roles & Permissions** → a code-declared permission catalog, roles and grants, enforced on every endpoint.
- **Users module** → list, create, edit, deactivate, invitations, role assignment (the reference module to copy).
- **Deployment ready** → Docker, VPS *(planned)*.

**Included right now**
- Backend → Django 5.2, DRF, cookie-JWT auth, RBAC, Celery jobs, `drf-spectacular` (Swagger UI), health probes under `/api/health/`.
- Frontend → Next.js 16, React 19, Tailwind 4, typed API client, app shell and design system, i18n.
- Dev Tools → `uv` (Python), Ruff (lint + format), ESLint, TypeScript strict, pytest, Vitest, CI, development Docker Compose.

The complete built / not-built list is [Project Status](#project-status).

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

##

### Table of contents:

| No. | Topics |
| --- | ------ |
| 0. | [Tech Stack](#tech-stack) |
| 1 | [Getting Started](#getting-started) |
| 2 | [Folder Structure](#folder-structure) |
| 3 | [Documentation](#documentation) |
| 4 | [Architecture](#architecture) |
| 5 | [Project Status](#project-status) |
| 6 | [Using This As A Core](#using-this-as-a-core) |
| 7 | [Roadmap](#roadmap) |
| 8 | [Contributing](#contributing) |

<br>

#

## Tech Stack
> A modern tech stack for building scalable web applications.
- **Backend**: Django 5 + Django REST Framework (Python 3.12)
- **Frontend**: Next.js 16 (App Router) + React 19 + Tailwind CSS 4 + TypeScript
- **Database**: PostgreSQL 16 in the Compose stack and CI; plain `runserver` defaults to SQLite (via `DATABASE_URL`; ADR-0005)
- **API Docs**: OpenAPI 3 via drf-spectacular (Swagger UI at `/api/docs/`)
- **Tooling**: uv, Ruff, ESLint

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Getting Started

**Quick start — one command** (`scripts/setup.sh`, BUILD_ORDER 4.1):
```sh
git clone https://github.com/ayush-sleeping/DjangoBaseX.git my-product && cd my-product
./scripts/setup.sh
```
It needs Docker with Compose v2, and `python3` 3.9 or newer on the host (the one stock macOS ships
is enough): setup writes the env files with it before anything else is installed.

It checks Docker, names the stack after the directory (`my-product-dev`), writes `.env`,
`backend/.env` and `frontend/.env.local`, generates every secret, picks free ports, starts PostgreSQL
16 and Redis, migrates, creates the first account (`admin@example.com`), starts both apps, and waits
until they answer. Then it prints the URLs and the development sign-in. Re-running it is safe: it
keeps every secret and port it already chose. No Docker? Use `./scripts/setup.sh --no-docker`, which
does the same on the host with SQLite and prints how to start the two dev servers.

Day to day: `docker compose up -d --wait` and `docker compose down`. After pulling new migrations,
`docker compose run --rm backend uv run --frozen python manage.py migrate` (the stack never migrates
on start). After changing `package.json`, use `docker compose up --build -V`. This is a
**development** stack only: `runserver`, `next dev`, ports on `127.0.0.1`. A plain `runserver` on the
host still uses SQLite (ADR-0005).

**By hand, without Docker — prerequisites**
- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 + the virtualenv for you) — `brew install uv`
- Node.js 20+ and npm

1. **Clone the repo:**
   ```sh
   git clone https://github.com/ayush-sleeping/DjangoBaseX.git
   cd DjangoBaseX
   ```

2. **Backend — install dependencies:**
   ```sh
   cd backend
   uv sync            # installs Python 3.12 if missing, creates .venv, installs deps
   ```

3. **Backend — configure environment:**
   ```sh
   cp .env.example .env
   # generate a SECRET_KEY and paste it into .env
   uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
   - SQLite is used by default. For PostgreSQL set `DATABASE_URL=postgres://user:pass@localhost:5432/djangobasex`.

4. **Backend — run migrations and create an admin user:**
   ```sh
   uv run python manage.py migrate
   uv run python manage.py createsuperuser
   ```

5. **Backend — start the Django server:**
   ```sh
   uv run python manage.py runserver
   ```

6. **Frontend — install dependencies** (new terminal):
   ```sh
   cd frontend
   npm install
   ```

7. **Frontend — configure environment:**
   ```sh
   cp .env.example .env.local
   ```
   - `NEXT_PUBLIC_API_URL` defaults to `http://localhost:8000`.

8. **Frontend — start the Next.js dev server:**
   ```sh
   npm run dev
   ```

9. **Access the app:**
   - Frontend: [http://localhost:3000](http://localhost:3000) — shows live backend health
   - Backend health: [http://localhost:8000/api/health/](http://localhost:8000/api/health/)
   - API docs (Swagger): [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/)
   - Django admin: [http://localhost:8000/admin/](http://localhost:8000/admin/)

10. **Run code quality checks:**
    - Ruff (backend lint + format):
      ```sh
      cd backend && uv run ruff check . && uv run ruff format --check .
      ```
    - Django system checks:
      ```sh
      cd backend && uv run python manage.py check
      ```
    - Tests (backend — pytest; by default an in-memory database, cache and email, so safe to run any time; CI uses PostgreSQL 16):
      ```sh
      cd backend && uv run pytest
      ```
    - ESLint + TypeScript (frontend):
      ```sh
      cd frontend && npm run lint && npm run typecheck
      ```

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Folder Structure
```
DjangoBaseX/
├── backend/                     # Django 5 + DRF API
│   ├── config/                  # Project package (settings, urls, asgi, wsgi)
│   │   ├── settings.py          # All settings; env values via django-environ
│   │   └── urls.py              # root URLconf: admin, health, schema, docs, plus core/users/rbac and registry routes
│   ├── core/  users/  rbac/     # The platform layer (ADR-0010): registry, API gate, jobs, auth, RBAC, users
│   ├── project/                 # This product's code; registers through core.registry
│   ├── plugins/                 # Plugins (git submodules), discovered from plugin.toml
│   ├── tests/                   # pytest: architecture tests, harness, platform tests
│   ├── manage.py
│   ├── pyproject.toml           # deps + Ruff config (uv-managed)
│   ├── uv.lock
│   └── .env.example
├── frontend/                    # Next.js 16 App Router
│   ├── src/
│   │   ├── app/                 # Routes: (core)/, (project)/, (plugins)/[plugin]/[[...slug]]
│   │   ├── core/lib/api.ts      # Typed fetch wrapper; every API call goes through it
│   │   ├── project/             # This product's UI
│   │   └── plugins/             # Plugin frontends (symlinks) + registry.generated.ts
│   ├── public/
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   └── .env.example
├── scripts/                     # setup.sh, core_doctor.py, plugins.py (new / link / list / registry)
├── docker-compose.yml           # Development stack: PostgreSQL, Redis, both apps, Celery worker
├── core.manifest.json           # Core file hashes, checked by core_doctor.py
├── VERSION
├── .github/workflows/           # ci.yml, core-guard.yml
├── .claude/                     # Agent skills, subagents, hooks
├── examples/plugins/notes/      # The example plugin; never loaded, installed by CI
├── documentation/               # All project docs — start at INDEX.md
│   ├── INDEX.md                 # The doc map
│   ├── ONBOARDING.md            # First day, end to end
│   ├── NEW_PROJECT.md           # Starting a product from this boilerplate
│   ├── UPGRADING.md             # Taking a core update into a product
│   ├── ADR.md + adr/            # Architecture decisions, numbered and immutable
│   ├── core/                    # How built subsystems work
│   ├── DAILY_CHANGES.md · VERSION_SUMMARY.md   # Change log; shippable features by version
│   ├── PURPOSE.md               # What this is for; the tie-breaker when designs conflict
│   ├── INVARIANTS.md · DOMAIN.md · ARCHITECTURE.md   # Rules that never break; vocabulary; the system map
│   ├── CODE_STANDARDS.md · UI_STANDARDS.md · TESTING.md · SECURITY.md   # Standards hubs
│   ├── PRODUCTION.md · RELEASE.md · DEFINITION_OF_DONE.md   # Ops hubs and the done checklist
│   ├── system-design/           # Data model, RBAC, API, security, Django/Next.js, deployment
│   └── planning/                # Intent: build order, architecture plan, tech debt, R&D
├── AGENTS.md                    # Operating contract — rules, gate, boundaries
├── CLAUDE.md · GEMINI.md        # Agent entry points; import AGENTS.md
├── .editorconfig
├── .gitignore
├── LICENSE
└── README.md
```

> The layout follows the [architecture plan](documentation/planning/CORE_ARCHITECTURE_PLAN.md):
> the platform never imports `project/` or a plugin, and both plug in through `core.registry`.

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Documentation

**Start at [`documentation/INDEX.md`](documentation/INDEX.md)** — it is the doc map, and it tells you
which single file to read for the area you are working on rather than making you read everything.

| I want to… | Read |
|------------|------|
| **Understand what this is for, and why** | [`documentation/PURPOSE.md`](documentation/PURPOSE.md) |
| Understand the repo end to end, day one | [`documentation/ONBOARDING.md`](documentation/ONBOARDING.md) |
| **Start a new product from this boilerplate** | [`documentation/NEW_PROJECT.md`](documentation/NEW_PROJECT.md) |
| Take a core update into my product | [`documentation/UPGRADING.md`](documentation/UPGRADING.md) |
| Know what to build next, concretely | [`documentation/planning/BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md) |
| Write backend code | [`documentation/system-design/DJANGO_STANDARDS.md`](documentation/system-design/DJANGO_STANDARDS.md) |
| Write frontend code | [`documentation/system-design/NEXTJS_STANDARDS.md`](documentation/system-design/NEXTJS_STANDARDS.md) |
| Design a model — ⚠️ 5 decisions before the first migration | [`documentation/system-design/DATA_MODEL.md`](documentation/system-design/DATA_MODEL.md) |
| Add an endpoint · permissions · security | [`API_DESIGN`](documentation/system-design/API_DESIGN.md) · [`RBAC_DESIGN`](documentation/system-design/RBAC_DESIGN.md) · [`SECURITY`](documentation/system-design/SECURITY.md) |
| Change the schema | [`documentation/system-design/DATABASE_MIGRATIONS.md`](documentation/system-design/DATABASE_MIGRATIONS.md) |
| Know **why** something is built this way | [`documentation/ADR.md`](documentation/ADR.md) |
| Find a known gap before reporting it | [`documentation/planning/TECH_DEBT.md`](documentation/planning/TECH_DEBT.md) |

**Working here with an AI agent?** [`AGENTS.md`](AGENTS.md) is the operating contract — rules,
the verification gate, layer boundaries and where each kind of change gets recorded. `CLAUDE.md`
imports it, so it loads automatically in Claude Code. Read it before the first change.

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Architecture

Three layers, so the platform can be reused while products and teams stay independent. The full
design is [`documentation/planning/CORE_ARCHITECTURE_PLAN.md`](documentation/planning/CORE_ARCHITECTURE_PLAN.md).

| Layer | What it is | Who owns it |
|-------|-----------|-------------|
| **`core/`** (with `users/`, `rbac/`) | The reusable platform — registry, API gate, settings, jobs, auth, RBAC, users (ADR-0010) | the boilerplate maintainer |
| **`project/`** | This product's code | the team that copied the boilerplate |
| **`plugins/`** | Self-contained features, **one GitHub repo each**, mounted as git submodules | one team per plugin |

**The rule that makes it work:** dependencies point inward, registration points outward. `core`
never imports `project` or a plugin — it exposes registries, and the others **register into them**
at boot through `AppConfig.ready()`. Core knows a nav section exists without ever knowing the
plugin's name.

```
Browser ──► Next.js 16 (App Router)  ──►  Django 5.2 + DRF  ──►  PostgreSQL
            src/core/lib/api.ts                /api/…                  (SQLite: bare runserver)
            the only module that
            makes HTTP calls
```

Every boundary above is enforced by a test rather than by convention — see
[`documentation/TESTING.md`](documentation/TESTING.md).

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Project Status

Stated plainly, because assuming otherwise wastes time.

**✅ Works today**
- Django 5.2 + DRF, `/api/health/`, OpenAPI schema and Swagger UI, Django admin
- CORS/CSRF configured for a separate-origin frontend, DRF throttling, every endpoint denied unless it declares its permissions
- Next.js 16 + React 19 + Tailwind 4, typed API wrapper, home page reading live backend health
- `uv` + Ruff on the backend, ESLint + strict TypeScript on the frontend
- **Sign in** — cookie-JWT auth per [ADR-0009](documentation/adr/0009-jwt-in-httponly-cookies.md): login, refresh with rotation and reuse detection, logout, sign-out-everywhere-else, `/api/auth/me/`, password reset by email (single-use links; any password change signs out every session), per-address+IP throttling and progressive lockout, TOTP two-factor with recovery codes and re-auth for sensitive actions, and minimal pages at `/login`, `/forgot-password`, `/reset-password` and `/account/security`
- **Permissions (RBAC engine)** — a code-declared catalog seeded to the database, roles and grants with an audit trail, a cached `has_perm` with an audited superuser bypass, `has_permission(...)` for views, `visible_to()` scoping, and boot checks for a shared cache and a single grant path; a declarative gate on every endpoint (undeclared = denied); system roles `administrator` / `staff`; the roles API and a roles screen at `/settings/roles`
- **Production guard rails** — `APP_ENV` classification and a boot refusal that lists every unsafe setting at once; request ids on every response and in error bodies; JSON logs with one scrubber
- **Users module** (the reference module to copy) — list/search, create (set-your-password email), edit, deactivate/activate (sessions revoked), sign-out-everywhere, role assignment; **invitations** with accept-and-sign-in; `manage.py bootstrap_admin` for account one
- A custom `users.User` (email login, no username) as `AUTH_USER_MODEL` — [ADR-0008](documentation/adr/0008-custom-user-model-email-identity.md)
- `docker compose up` development stack with live reload on both halves, plus Redis as the shared cache
- Argon2 password hashing; a proxy-aware `client_ip()` with tests; `/admin/` only when `ADMIN_ENABLED`
- **Plugins** — drop a directory with a `plugin.toml` into `backend/plugins/` and it is installed: its models, permissions, API routes, navigation and frontend pages mount through the registries, and architecture tests keep it inside its prefixes. `scripts/plugins.py` scaffolds and links them; [`examples/plugins/notes`](examples/plugins/notes/README.md) is a worked example that CI installs on every push
- Full documentation set, 15 ADRs, an agent contract, and a ranked tech-debt register

**❌ Not built yet**
- **Domain models** — the platform holds identity and RBAC only; no organisation model ([ADR-0011](documentation/adr/0011-no-organisation-in-core.md))
- **Browser end-to-end tests** — none yet; the backend has a pytest suite and the frontend a Vitest + MSW suite (8.1). **CI** (`.github/workflows/ci.yml`) runs the whole gate on every push and PR, backend tests on PostgreSQL 16
- **Not yet in the app shell** — static security headers, logos and host-matched identity (8.5b); the per-request nonce CSP and runtime brand colours are built (8.5). The shell itself is built: the bootstrap call (`/api/me/bootstrap/`), the fail-closed permission provider, a server-built menu that is also the default-deny route gate, and the session-marker proxy exist (`BUILD_ORDER` 8.2); the sidebar and design system are built (8.3); CSP and runtime branding are not (8.5)
- **Production Docker / deployment** — no topology (the Compose stack is for development). See [`documentation/system-design/DEPLOYMENT.md`](documentation/system-design/DEPLOYMENT.md) § 0

**✅ Both foundational decisions are settled:** custom `User` model ([ADR-0008](documentation/adr/0008-custom-user-model-email-identity.md))
and JWT in `httpOnly` cookies backed by DB session rows ([ADR-0009](documentation/adr/0009-jwt-in-httponly-cookies.md)).

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Using This As A Core

The point of this repository is that a new project starts from it in minutes.

> ⚠️ **Do not press "Use this template".** A template repo shares no git history, so `git merge
> core/main` has no common ancestor and your copy can **never** take a core update. Clone and
> re-origin instead:

```sh
git clone https://github.com/ayush-sleeping/DjangoBaseX.git my-product
cd my-product
git remote rename origin core                 # upstream — this is how updates arrive
git remote add origin git@github.com:<owner>/my-product.git
git push -u origin main
```

Then follow [`documentation/NEW_PROJECT.md`](documentation/NEW_PROJECT.md) — the rename checklist,
a **fresh `SECRET_KEY`** (two products sharing one is a cross-product session-forgery bug), and the
decisions to settle first.

Taking a core update later is `git fetch core && git merge core/main` —
[`documentation/UPGRADING.md`](documentation/UPGRADING.md) explains what a conflict tells you.

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Roadmap
Built by accumulation, one module at a time.

> **The executable version of this table is [`documentation/planning/BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md)** — numbered tasks with acceptance criteria, in dependency order. Start there; this table is the summary.

| Capability | How it is built here | Status |
|------------|----------------------|--------|
| Authentication | Cookie JWT — access/refresh, rotation, DB-backed sessions | ✅ (1.1) |
| Roles & permissions | Code-declared catalog + the `core/api/` gate + object-level scoping | ✅ (1.2–1.4) |
| Admin UI | Next.js dashboard — data tables, forms, ShadCN | 🔄 app shell and design system (8.3); nonce CSP and brand colours (8.5); headers, logos ⬜ (8.5b) |
| Core CRUD modules | DRF viewsets + Next.js pages | 🔄 Users module (1.5) |
| Activity log | Append-only audit trail | ✅ audit engine (6.4) |
| Background jobs | Celery + Redis + Flower | ✅ Celery + beat, generated from the job registry (7.1); Flower not |
| Social login / 2FA | `pyotp` TOTP | 🔄 TOTP 2FA done (1.1d); social login not |
| Static analysis | mypy + Ruff | 🔄 Ruff done; mypy not |
| Test suite | pytest + pytest-django + factory_boy | ✅ backend (2.1–2.3), CI on PostgreSQL 16; frontend Vitest + MSW (8.1) |
| Containerisation | docker-compose (Django + Next + Postgres + Redis) | 🔄 dev stack done |
| Health check | `/api/health/` | ✅ |
| API docs | drf-spectacular | ✅ |

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Contributing

This repository is a **boilerplate**: a change to it is inherited by every product copied from it,
including ones that already shipped. That is why the rules are stricter than a normal project's.

**Before you start**
- Read [`AGENTS.md`](AGENTS.md) — the operating contract. It applies to humans and AI agents alike
- Check [`documentation/ADR.md`](documentation/ADR.md) before changing the *shape* of anything; a
  decision listed as **Accepted** is settled, and reopening it needs a new ADR, not a quiet edit
- Check [`documentation/planning/TECH_DEBT.md`](documentation/planning/TECH_DEBT.md) before reporting
  a problem as new

**While you work**
- **Never commit without being asked.** Conventional commits: `<type>(<scope>): <description>`
- **Never add AI attribution** to a commit message — no `Co-Authored-By`, no "Generated with"
- Keep changes atomic. Match the surrounding code; don't introduce a second way of doing something
- Log the change in [`documentation/DAILY_CHANGES.md`](documentation/DAILY_CHANGES.md) **in the same
  commit as the code**, not afterwards

**Before you call it done — the verification gate**
```sh
cd backend  && uv run ruff check . && uv run ruff format --check . && uv run python manage.py check
cd backend  && uv run python manage.py makemigrations --check --dry-run   # after ANY model change
cd backend  && uv run pytest
cd frontend && npm run lint && npm run typecheck
```
CI runs the same gate on every push and PR, but run it before you push: a red CI is a slower way to learn the same thing. Report their real output,
including failures — a green summary over a red run is the one unrecoverable mistake.

**Adding to the core**
A change to the platform needs a reason that applies to **more than one product**. If it only serves
yours, it belongs in your own copy. If the core genuinely cannot express what you need, that is a
request for a **seam** — and everyone gets it, not just you. Adding a seam is almost always better
than adding a special case.

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>
