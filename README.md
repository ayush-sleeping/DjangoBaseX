<div id="top"></div>

## 🚀 &nbsp; DjangoBaseX
> A Django 5 + Next.js Full Stack Starter Boilerplate.

The Django / Next.js sibling of [LaraBaseX](https://github.com/ayush-sleeping/LaraBaseX): a secure, modular, production-ready base project using **Django 5 + Django REST Framework** for the API and **Next.js (App Router)** for the frontend — ideal for building scalable web applications with a Python backend and a TypeScript frontend.

> **Status:** early scaffold. The two halves run and talk to each other; features are added module-by-module following the [Django-Nextjs-Journey](https://github.com/ayush-sleeping/Django-Nextjs-Journey) Level 2 plan.

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
| 3 | [Roadmap](#roadmap) |

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
├── .editorconfig
├── .gitignore
├── LICENSE
└── README.md
```

<p align="right"><a href="#top"><img src="https://img.shields.io/badge/-Back%20to%20Top-092E20?style=for-the-badge" /></a></p>

<br>

#

## Roadmap
Built by accumulation, one module at a time (see the [Journey's North Star table](https://github.com/ayush-sleeping/Django-Nextjs-Journey/tree/main/Projects)):

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
