# Deployment

> ## ⚠️ § 0 — Read this first
>
> **This application has never been deployed.** There is no staging environment, no production
> environment, no process manager, no reverse proxy, and no container setup. This document is
> a **gap analysis and the shape of a runbook** — not steps you can follow today.
>
> **Do not deploy this to any internet-reachable environment until the blockers below are closed.**

---

## 0. Blockers — fix before any deploy

| # | Blocker | Required change |
|---|---------|-----------------|
| 1 | **Authentication is incomplete** | Login, refresh, logout, `/me`, password reset, throttling, progressive lockout, TOTP two-factor and re-auth exist (ADR-0009). No invitation flow yet, so the first account needs `createsuperuser`. Set `MFA_ENCRYPTION_KEY` before anyone enrols, and do not rotate it (`TECH_DEBT` DB-33). `forgot/` is a timing oracle until mail is enqueued (DB-32). No RBAC either (1.2–1.4) |
| 2 | **A young test suite** | CI (`.github/workflows/ci.yml`) runs the `AGENTS.md` § 2 gate on every push and PR, with backend tests on PostgreSQL 16 — but coverage is thin until Phase 1's features land with their tests, and there are no frontend tests. `TECH_DEBT` **DB-5** |
| 3 | **No production topology** | No release image or production Compose (the `Dockerfile.dev` files and `docker-compose.yml` are a development stack: `runserver`, `next dev`, source bind mounts), no Nginx/TLS terminator, no WSGI/ASGI server config, no static-file strategy. `runserver` is a development server and must never face the internet |
| 4 | **No monitoring yet; logging is structured** | JSON logs with request ids and one scrubber since 6.1 (`LOG_FORMAT=json` is enforced in production). No error tracker, metrics or aggregation yet (6.2+) |
| 5 | **SQLite is the default** | `DATABASE_URL` must be set to PostgreSQL. A deploy that forgets it silently runs on a file that vanishes with the container ([ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)) |
| 6 | ~~No `APP_ENV`-style guard on unsafe defaults~~ | **Fixed 2026-10-11 (`BUILD_ORDER` 5.1).** Set `APP_ENV=production` (or any non-development label): settings import then **refuses to boot** on `DEBUG`, placeholder or equal secrets, http/wildcard origins, console mail, a per-process cache, SQLite, a non-https `FRONTEND_BASE_URL` or non-JSON logs, listing every problem. Run `python -m core.config_audit` against the target environment before deploying |

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
| `CACHE_URL` | unset (LocMem) — Docker sets Redis | **A shared Redis URL.** Throttles, lockout and session revocation live in the cache; LocMem makes each of them per worker (`AUTH_BLUEPRINT.md` § 17.4) |
| `CELERY_BROKER_URL` | unset (`memory://`, boots without a broker; nothing consumes it). Docker sets Redis db 1 | **A Redis broker URL.** `dbx.jobs.E015` refuses `memory://` or unset when `APP_ENV` is production-like. Production: a Redis with `noeviction` and append-only persistence, not the LRU cache instance ([`OPERATIONS.md`](OPERATIONS.md)): an evicted message is a job that silently never ran |
| `CELERY_RESULT_BACKEND` | unset | Unset. Job history is the run record, not Celery results ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 3) |
| `CELERY_VISIBILITY_TIMEOUT` | `3600` | Above the longest job `time_limit` (`dbx.jobs.E011`), or Redis redelivers a running job to a second worker |
| `CELERY_TIMEZONE` | `UTC` | `UTC`. Cron schedules are read in it |
| `TRUSTED_PROXY_COUNT` | `0` | **The number of proxies in front of the app.** Left at `0` behind a load balancer, every user shares one IP and one attacker locks everyone out (§ 17.3) |
| `ADMIN_ENABLED` | defaults to `DEBUG` | **`False`** unless you deliberately want `/admin/` reachable (Ch. 20) |
| `EMAIL_BACKEND` / `DEFAULT_FROM_EMAIL` | console / `no-reply@example.com` | A real mail backend and a sender on your domain |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | The public frontend URL, **https**. Emailed links point here |

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
   `migrate` also **syncs the beat schedule from the job registry** (`post_migrate`). A beat row
   whose name a job needs but which the registry does not own is reported, never adopted:
   `migrate` logs an ERROR `core.job.schedule_conflict`, and `manage.py sync_schedules` prints
   `conflict <name>: a PeriodicTask with this name exists and the registry does not own it. Delete
   or rename it, then sync again.` Do that, then run `manage.py sync_schedules`
   (`--dry-run` first shows the diff).
3. `uv run python manage.py collectstatic --noinput` — for the admin and Swagger UI assets
4. Serve via **Gunicorn or Uvicorn**, never `runserver`
5. Reverse proxy (Nginx/Caddy) terminating TLS and serving `STATIC_ROOT`
6. **Background jobs are required, not optional** (BUILD_ORDER 7.1, ADR-0012). Run:
   - **Workers that together consume every declared queue**: today `default,bulk`
     (`celery -A config worker -Q default,bulk`). A queue nobody consumes is work that never runs,
     and nothing raises. `tests/architecture/test_every_queue_has_a_worker.py` checks the shipped
     compose file; keep any other topology in line with it. Give each worker a stop grace period
     longer than the longest soft time limit it runs (840 s today).
   - **Exactly one beat** (`celery -A config beat`). (The development compose starts it only with
     `--profile scheduler`; a deployment always runs it.) Two double every scheduled job; when you
     replace it, stop the old one before starting the new one.
   - Without them, the auth retention sweep (`users.auth_cleanup`, formerly a cron entry) never
     runs, and `users_login_attempt` grows with attack traffic. No crontab entry is needed any more.

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
