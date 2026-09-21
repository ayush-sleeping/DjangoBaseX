# Roadmap

**Intent, not current state.** A row marked ⬜ is *not built* — check the code before assuming
otherwise. What exists today is described in [`../core/ARCHITECTURE.md`](../core/ARCHITECTURE.md).

Built by accumulation, one module at a time, tracking the
[Django-Nextjs-Journey](https://github.com/ayush-sleeping/Django-Nextjs-Journey) Level 2 plan.

---

## Status

| Capability | How it is built here | Status |
|------------|----------------------|--------|
| Health check | `/api/health/` | ✅ |
| API docs | drf-spectacular at `/api/docs/` | ✅ |
| Lint + format | Ruff | ✅ |
| Python types | mypy | ⬜ |
| Authentication | Cookie JWT — access/refresh, rotation, DB-backed sessions | ⬜ |
| Roles & permissions | Code-declared catalog + DRF permission classes + object-level scoping | ⬜ |
| Admin UI | Next.js dashboard — data tables, forms, ShadCN | ⬜ |
| Core CRUD modules | DRF viewsets + Next.js pages | ⬜ |
| Activity log | Append-only audit trail | ⬜ |
| Background jobs | Celery + Redis + Flower | ⬜ |
| Social login / 2FA | django-allauth + `pyotp` TOTP | ⬜ |
| Test suite | pytest + pytest-django + factory_boy | ⬜ |
| Containerisation | docker-compose — Django + Next + Postgres + Redis | ⬜ |

---

## Decide before building

Two questions that get answered badly if they get answered by accident:

### 1. Session auth or JWT — not both

`config/settings.py` currently sets `SessionAuthentication`, and the table above plans SimpleJWT.
Those are different models with different CSRF, CORS and refresh implications. Landing the first
authenticated endpoint settles it de facto, so **settle it deliberately first and write the ADR**.
Tracked as [`TECH_DEBT.md`](TECH_DEBT.md) **DB-1**.

### 2. Tests before or after the first real feature

There are zero tests. Every module added before the suite exists is a module whose tests get written
later, or never — and "later" has a known success rate. Adding pytest + pytest-django is cheap now
and gets more expensive with every module.

**Recommendation: tests first.** The suite is a few hours of work at this size, and every feature
after it arrives covered.

---

## Suggested order

Dependency-ordered, not priority-ordered — each step is hard to do well before the one above it.

1. **pytest + pytest-django + factory_boy**, and a CI workflow that runs the `AGENTS.md` § 2 gate.
   Everything below is safer with this in place, and it is the cheapest it will ever be
2. **Resolve DB-1** (auth model) and write the ADR
3. **Auth** — SimpleJWT, `/me`, refresh rotation, and the frontend half in `src/lib/api.ts`
4. **RBAC** — groups, permission classes, object-level checks. Fail closed, like the DRF default
5. **A custom `User` model** — ⚠️ **if this is ever wanted, it must happen before the first migration
   that references `AUTH_USER_MODEL`.** Swapping it later is one of the genuinely painful migrations
   in Django. Decide now even if the answer is "the default is fine"
6. **First CRUD module** (Users), backend and frontend, as the pattern every later module copies
7. **Type generation** from `/api/schema/` into the frontend (`TECH_DEBT` **DB-4**)
8. **Docker Compose** — Postgres + Redis, which unblocks realistic local development and CI
9. **Celery + Redis**, then the activity log, then 2FA/social login
