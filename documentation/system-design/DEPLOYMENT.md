# Deployment

> ## ⚠️ § 0 — Read this first
>
> **This application has never been deployed.** There is no staging environment, no production
> environment, no CI, no process manager, no reverse proxy, and no container setup. This document is
> a **gap analysis and the shape of a runbook** — not steps you can follow today.
>
> **Do not deploy this to any internet-reachable environment until the blockers below are closed.**

---

## 0. Blockers — fix before any deploy

| # | Blocker | Required change |
|---|---------|-----------------|
| 1 | **No authentication at all** | There is no login, no token, no `/me`. DRF's `IsAuthenticated` default fails closed, so the API is effectively closed rather than open — but there is also nothing to protect yet. A product deploying from this must land auth first. See [ROADMAP](../planning/ROADMAP.md) |
| 2 | **No tests, no CI** | Nothing verifies that a deploy has not broken something. The verification gate in `AGENTS.md` § 2 is run by a person, by hand, when they remember. `TECH_DEBT` **DB-5** / **DB-6** |
| 3 | **No production topology** | No Dockerfile, no Compose, no Nginx/TLS terminator, no WSGI/ASGI server config, no static-file strategy. `runserver` is a development server and must never face the internet |
| 4 | **No monitoring or structured logging** | `settings.py` has no `LOGGING` config, so a 500 in production goes to stdout and is lost. No error tracker, no aggregation, no retention |
| 5 | **SQLite is the default** | `DATABASE_URL` must be set to PostgreSQL. A deploy that forgets it silently runs on a file that vanishes with the container ([ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)) |
| 6 | **No `APP_ENV`-style guard on unsafe defaults** | Nothing stops `DEBUG=True` or a placeholder `SECRET_KEY` reaching production. A default that is safe locally and unsafe in production is invisible until something asserts it. `TECH_DEBT` **DB-7** |

---

## 1. Configuration that must change per environment

**Not defects — required settings.** Every one comes from `.env` via `django-environ`.

### Backend

| Key | Development | Production |
|-----|-------------|-----------|
| `SECRET_KEY` | anything | **Unique per environment, 50+ random chars, never reused.** Two apps sharing one means a session signed by either is accepted by both |
| `DEBUG` | `True` | **`False`.** `True` serves a full traceback with settings to any visitor |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | The real hostnames. Never `*` |
| `DATABASE_URL` | unset (SQLite) | **A PostgreSQL URL** |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | The real frontend origin, **https**. Never `*` with credentials |
| `CSRF_TRUSTED_ORIGINS` | `http://localhost:3000` | The real frontend origin, **https** |

### Frontend

| Key | Note |
|-----|------|
| `NEXT_PUBLIC_API_URL` | The public API origin, **https**. Inlined into the client bundle — public by design |

### Django settings that need adding for production 🔜

None of these are in `config/settings.py` today:

```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")   # if behind a proxy
```

`uv run python manage.py check --deploy` lists what is missing. **Run it — it is free and it is the
closest thing to a production readiness check this project currently has.**

---

## 2. What a deploy will have to do

Sketch, for when the topology is decided:

**Backend**
1. `uv sync --frozen` — install from the lock, fail rather than re-resolve
2. `uv run python manage.py migrate`
3. `uv run python manage.py collectstatic --noinput` — for the admin and Swagger UI assets
4. Serve via **Gunicorn or Uvicorn**, never `runserver`
5. Reverse proxy (Nginx/Caddy) terminating TLS and serving `STATIC_ROOT`

**Frontend**
1. `npm ci` — from the lockfile, not `npm install`
2. `npm run build`
3. `npm run start`, or a static/edge target if the app allows it

**Both**
- `NEXT_PUBLIC_API_URL` is **baked in at build time**. Changing the API origin requires a rebuild,
  not a restart. This surprises people exactly once, in production.

---

## 3. Health checks

| Endpoint | Use |
|----------|-----|
| `GET /api/health/` | Liveness. Public, no auth |

🔜 There is no readiness probe — nothing that checks the database is reachable. A liveness probe that
answers while the database is down will keep a broken instance in the load balancer. Worth adding
before the first deploy.

---

## 4. Pre-deploy checklist

```bash
cd backend
uv run python manage.py check --deploy          # security settings
uv run python manage.py makemigrations --check --dry-run   # no un-migrated model changes
uv run ruff check . && uv run ruff format --check .

cd ../frontend
npm run lint && npx tsc --noEmit && npm run build
```

Then, by hand, confirm: `DEBUG=False` · `SECRET_KEY` is unique to this environment ·
`ALLOWED_HOSTS` is not `*` · `DATABASE_URL` points at PostgreSQL · CORS/CSRF origins are https and
exact · no `.env` file is in the image.
