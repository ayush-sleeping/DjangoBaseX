# Tech Debt

**Every known defect, gap and deferred decision — ranked.** Check here before reporting something as
a new discovery; if it is listed, it is known.

Adding a row is part of the same change that creates the debt (`AGENTS.md` § 4). A row is closed by
striking it through with the date, not by deleting it — a deleted row loses the evidence that the
problem was real.

**Ranking:** 🔴 blocks a deploy · 🟠 will cause a real bug · 🟡 costs time repeatedly · 🟢 tidiness

---

| ID | Pri | Title | Detail |
|----|-----|-------|--------|
| **DB-1** | 🔴 | **Auth model undecided — session vs JWT** | `config/settings.py` sets `SessionAuthentication`; [ROADMAP](ROADMAP.md) plans SimpleJWT. Different CSRF, CORS and refresh implications. **Whichever the first authenticated endpoint uses settles it by accident.** Decide deliberately and write the ADR *before* building auth |
| **DB-5** | 🔴 | **No test suite** | `backend/core/tests.py` is Django's stub; the frontend has no runner installed. Nothing can fail a build. Every module added before the suite exists is a module whose tests get written "later" |
| **DB-6** | 🔴 | **No CI** | No `.github/workflows/`. The `AGENTS.md` § 2 gate runs only when a person remembers. A broken `npm run build` or a missing migration can sit unnoticed indefinitely |
| **DB-7** | 🟠 | **Nothing guards unsafe production defaults** | No `APP_ENV`-style check refuses `DEBUG=True` or a placeholder `SECRET_KEY` outside development. A default that is safe locally and unsafe in production is invisible until something asserts it |
| **DB-8** | 🟠 | **No production security settings** | `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HSTS are all absent from `settings.py`. `manage.py check --deploy` lists them |
| **DB-9** | 🟠 | **No `LOGGING` configuration** | No structured logging, no request correlation, no destination. A 500 in production goes to stdout and is lost |
| **DB-10** | 🟠 | **Custom `User` model decision still open** | If a custom user model is ever wanted it must land **before** the first migration referencing `AUTH_USER_MODEL`. Swapping later is one of Django's genuinely painful migrations. Decide now, even if the answer is "the default is fine" |
| **DB-4** | 🟡 | **Frontend types are hand-written** | The backend publishes OpenAPI at `/api/schema/`, and the frontend does not consume it. Hand-written response types in `src/lib/` drift from the API silently — they typecheck against yesterday's contract while being wrong |
| **DB-2** | 🟡 | **No `typecheck` npm script** | The gate is `npx tsc --noEmit`, which is easy to skip because it is not a named script. Add `"typecheck": "tsc --noEmit"` to `frontend/package.json` |
| **DB-3** | 🟡 | **No Python type checking** | Ruff does not type-check. `mypy` (with `django-stubs`) is on the [roadmap](ROADMAP.md) and is a separate decision from [ADR-0004](../adr/0004-ruff-is-the-only-python-tool.md) |
| **DB-11** | 🟡 | **No readiness probe** | `/api/health/` answers without checking the database. A liveness probe that stays green while the DB is down keeps a broken instance in the load balancer |
| **DB-12** | 🟡 | **Postgres-only features pass locally on SQLite** | [ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md) accepts this. Nothing catches it — no tests, no CI. Mitigated once CI runs against PostgreSQL 16 |
| **DB-13** | 🟢 | **No seeders or fixtures** | Resetting local data means `createsuperuser` by hand. A `seed` management command would make it one repeatable step |
| **DB-14** | 🟢 | **`known-first-party` is a manual step** | Each new Django app must be added to `backend/pyproject.toml`. Forgetting it makes Ruff fail on files nobody touched — a misleading symptom for a trivial cause |
| **DB-15** | 🟠 | **`/admin/` is an unguarded second auth system** | `config/urls.py` mounts it unconditionally. It authenticates by session (not `CookieJWTAuthentication`), authorizes on `auth_permission` (not the RBAC catalog), sits outside `/api/` so `dbx.E001` and the route test never see it, and writing `rbac_*` rows through it bypasses the elevated-role and last-superuser guards **and writes no `ActivityLog`**. Fixed by `BUILD_ORDER` **1.7** — `ADMIN_ENABLED`, and the `rbac` models not registered. See `AUTH_BLUEPRINT.md` Ch. 20 |
| **DB-16** | 🟡 | **No scheduler, so retention runs by cron** | `AUTH_BLUEPRINT.md` § 19.2 needs `auth_cleanup` run daily; `users_login_attempt` grows with attack traffic rather than user count. Celery is Phase 2, so until then this is a crontab entry the deployer has to remember — which is to say, an unenforced requirement |
| **DB-17** | 🟡 | **A shared cache is a correctness requirement, not a performance one** | The permission-version counter, session liveness and every throttle live in `django.core.cache`, which defaults to per-process `LocMemCache`. `dbx.E005` (`BUILD_ORDER` **1.0**) refuses to boot that way with `DEBUG=False`, but until 1.0 lands nothing says so. `AUTH_BLUEPRINT.md` § 17.4 |

---

## Closed

_Nothing yet. When a row closes, move it here struck through with the date and what fixed it —
so the next person can see it was real, and how it was resolved._
