<div id="top"></div>

## 🚀 &nbsp; DjangoBaseX
> A Django 5 + Next.js Full Stack Starter Boilerplate.

The Django / Next.js sibling of [LaraBaseX](https://github.com/ayush-sleeping/LaraBaseX): a secure, modular, production-ready base project using **Django 5 + Django REST Framework** for the API and **Next.js (App Router)** for the frontend — ideal for building scalable web applications with a Python backend and a TypeScript frontend.

> **Status:** early scaffold with a settled architecture. The two halves run and talk to each other, and the **conventions, decisions and build order are fully documented** — see [`documentation/INDEX.md`](documentation/INDEX.md). Features are added module-by-module following the [Django-Nextjs-Journey](https://github.com/ayush-sleeping/Django-Nextjs-Journey) Level 2 plan.
>
> **Not deployable yet.** No auth, no RBAC, no tests, no CI, no Docker. That list is honest and tracked — see [Project Status](#project-status) and [`documentation/planning/TECH_DEBT.md`](documentation/planning/TECH_DEBT.md).

## Overview

**What DjangoBaseX Is**

A starter kit for developers who want to skip repetitive setup work and start building features right away.
- **Django 5 backend** → clean REST API architecture (DRF), OpenAPI docs, env-driven settings.
- **Next.js frontend** → App Router, TypeScript, Tailwind CSS, typed API client.
- **Security baked in** → CORS, CSRF, rate limiting (DRF throttling), secrets from `.env`.
- **Roles & Permissions** → Django groups + DRF permission classes *(planned)*.
- **Full CRUDs ready** → Users, Employees, Enquiries *(planned)*.
- **Deployment ready** → Docker, VPS *(planned)*.

**Included right now**
- Backend → Django 5.2, DRF, `django-cors-headers`, `django-environ`, `drf-spectacular` (Swagger UI), public `/api/health/` probe.
- Frontend → Next.js 16, React 19, Tailwind 4, `src/lib/api.ts` fetch wrapper, home page showing live backend health.
- Dev Tools → `uv` (Python), Ruff (lint + format), ESLint, TypeScript strict.

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
- **Database**: SQLite (default) / PostgreSQL (via `DATABASE_URL`)
- **API Docs**: OpenAPI 3 via drf-spectacular (Swagger UI at `/api/docs/`)
- **Tooling**: uv, Ruff, ESLint

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Getting Started

**Prerequisites**
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
   uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
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
    - ESLint + TypeScript (frontend):
      ```sh
      cd frontend && npm run lint && npx tsc --noEmit
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
│   │   └── urls.py              # /admin, /api/health, /api/schema, /api/docs
│   ├── core/                    # Base app: health probe, shared utilities
│   │   ├── views.py             # HealthView
│   │   └── urls.py
│   ├── manage.py
│   ├── pyproject.toml           # deps + Ruff config (uv-managed)
│   ├── uv.lock
│   └── .env.example
├── frontend/                    # Next.js 16 App Router
│   ├── src/
│   │   ├── app/                 # Routes (page.tsx = home w/ backend health)
│   │   └── lib/
│   │       └── api.ts           # Typed fetch wrapper for the Django API
│   ├── public/
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   └── .env.example
├── documentation/               # All project docs — start at INDEX.md
│   ├── INDEX.md                 # The doc map
│   ├── ONBOARDING.md            # First day, end to end
│   ├── NEW_PROJECT.md           # Starting a product from this boilerplate
│   ├── UPGRADING.md             # Taking a core update into a product
│   ├── ADR.md + adr/            # Architecture decisions, numbered and immutable
│   ├── core/                    # How built subsystems work
│   ├── VISION.md                # What this is for; the tie-breaker when designs conflict
│   ├── system-design/           # Data model, RBAC, API, security, Django/Next.js, deployment
│   └── planning/                # Intent: build order, architecture plan, tech debt, R&D
├── AGENTS.md                    # Operating contract — rules, gate, boundaries
├── CLAUDE.md                    # Agent entry point; imports AGENTS.md
├── .editorconfig
├── .gitignore
├── LICENSE
└── README.md
```

> `backend/project/` and `backend/plugins/` are part of the
> [architecture plan](documentation/planning/CORE_ARCHITECTURE_PLAN.md) and do not exist yet —
> Phase 0 creates them.

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Documentation

**Start at [`documentation/INDEX.md`](documentation/INDEX.md)** — it is the doc map, and it tells you
which single file to read for the area you are working on rather than making you read everything.

| I want to… | Read |
|------------|------|
| **Understand what this is for, and why** | [`documentation/VISION.md`](documentation/VISION.md) |
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
| **`core/`** | The reusable platform — auth, RBAC, users, settings | the boilerplate maintainer |
| **`project/`** | This product's code | the team that copied the boilerplate |
| **`plugins/`** | Self-contained features, **one GitHub repo each**, mounted as git submodules | one team per plugin |

**The rule that makes it work:** dependencies point inward, registration points outward. `core`
never imports `project` or a plugin — it exposes registries, and the others **register into them**
at boot through `AppConfig.ready()`. Core knows a nav section exists without ever knowing the
plugin's name.

```
Browser ──► Next.js 16 (App Router)  ──►  Django 5.2 + DRF  ──►  PostgreSQL
            src/lib/api.ts                /api/…                  (SQLite in dev)
            the only module that
            makes HTTP calls
```

Every boundary above is enforced by a test rather than by convention — see
[`documentation/planning/TESTING_STRATEGY.md`](documentation/planning/TESTING_STRATEGY.md).

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Project Status

Stated plainly, because assuming otherwise wastes time.

**✅ Works today**
- Django 5.2 + DRF, `/api/health/`, OpenAPI schema and Swagger UI, Django admin
- CORS/CSRF configured for a separate-origin frontend, DRF throttling, `IsAuthenticated` by default
- Next.js 16 + React 19 + Tailwind 4, typed API wrapper, home page reading live backend health
- `uv` + Ruff on the backend, ESLint + strict TypeScript on the frontend
- Full documentation set, 6 ADRs, an agent contract, and a ranked tech-debt register

**❌ Not built yet**
- **Authentication** — no login, no tokens, no `/me`
- **RBAC** — nothing beyond DRF's `IsAuthenticated` default
- **Models** — `backend/core/models.py` is empty; the only tables are Django's own
- **Tests** — zero, on both sides. **Nothing can fail a build**
- **CI** — no workflows
- **Docker / deployment** — no topology. See [`documentation/system-design/DEPLOYMENT.md`](documentation/system-design/DEPLOYMENT.md) § 0

**⚠️ Two decisions to settle before the first feature** — both get decided by accident otherwise, and
both are expensive to reverse:
1. **Session auth or JWT** — see [`documentation/planning/AUTH_RND.md`](documentation/planning/AUTH_RND.md)
2. **Custom `User` model or Django's** — must land **before** any migration references `AUTH_USER_MODEL`

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
Built by accumulation, one module at a time (see the [Journey's North Star table](https://github.com/ayush-sleeping/Django-Nextjs-Journey/tree/main/Projects)).

> **The executable version of this table is [`documentation/planning/BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md)** — numbered tasks with acceptance criteria, in dependency order. Start there; this table is the summary.

| LaraBaseX feature | DjangoBaseX equivalent | Status |
|-------------------|------------------------|--------|
| Sanctum auth | DRF SimpleJWT (access/refresh, blacklist, `/me`) | ⬜ |
| Spatie roles & permissions | Groups + DRF permission classes + object-level RBAC | ⬜ |
| Inertia + React admin | Next.js dashboard (data tables, forms, ShadCN) | ⬜ |
| Users / Employees / Enquiries CRUD | DRF viewsets + Next.js pages | ⬜ |
| Activity log | `django-simple-history` audit trail | ⬜ |
| Queues (Horizon) | Celery + Redis + Flower | ⬜ |
| Social login / 2FA | django-allauth + `pyotp` TOTP | ⬜ |
| PHPStan / Pint | mypy + Ruff | 🔄 Ruff done |
| Pest | pytest + pytest-django + factory_boy | ⬜ |
| Docker setup | docker-compose (Django + Next + Postgres + Redis) | ⬜ |
| Health check | `/api/health/` | ✅ |
| API docs (Swagger) | drf-spectacular | ✅ |

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
cd frontend && npm run lint && npx tsc --noEmit
```
There is **no test suite yet**, so these are the entire safety net. Report their real output,
including failures — a green summary over a red run is the one unrecoverable mistake.

**Adding to the core**
A change to the platform needs a reason that applies to **more than one product**. If it only serves
yours, it belongs in your own copy. If the core genuinely cannot express what you need, that is a
request for a **seam** — and everyone gets it, not just you. Adding a seam is almost always better
than adding a special case.

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>
