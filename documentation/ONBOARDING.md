# Onboarding

> **Status:** Guide — checked 2026-11-14 · hubs: [`PURPOSE.md`](PURPOSE.md), [`INVARIANTS.md`](INVARIANTS.md), [`TESTING.md`](TESTING.md), [`system-design/TRAPS.md`](system-design/TRAPS.md).

**First day on DjangoBaseX, end to end.** About 20 minutes to a running stack, plus reading.

If you only want the commands, [`../README.md`](../README.md) § Getting Started has them. This file
explains what you are looking at and what the rules are.

---

## 1. What this repository is

**A boilerplate — a production-ready Django + Next.js base project.**
Products get *copied from* it. It is not itself a product, and it must never acquire one's identity:
no client names, no domain models that serve a single product.

That framing explains most of the rules. A convention here is inherited by every copy, into
repositories with their own access lists, long after anyone remembers where it came from. So:

- **Treat the repo as public** even though it isn't. A secret committed once is in the history of
  every copy, and deleting the line does not remove it from history.
- **Decisions get written down** ([ADR-0001](adr/0001-record-architecture-decisions.md)). The person
  who questions a choice in a year will not be the person who made it.

---

## 2. Get it running

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/) (`brew install uv`) and Node.js 20+. That is
all — `uv` installs Python 3.12 itself.

```bash
# Backend
cd backend
uv sync                                   # installs Python 3.12, creates .venv, installs deps
cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
# paste that into SECRET_KEY in .env
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver         # :8000

# Frontend — new terminal
cd frontend
npm install
cp .env.example .env.local
npm run dev                               # :3000
```

**Check it worked:**

| URL | You should see |
|-----|----------------|
| http://localhost:3000 | The home page, showing **live** backend health — if it says the backend is down, the Django server is not running |
| http://localhost:8000/api/health/ | A JSON health response |
| http://localhost:8000/api/docs/ | Swagger UI |
| http://localhost:8000/admin/ | Django admin — sign in with the superuser you just made |

### If something goes wrong

| Symptom | Cause |
|---------|-------|
| `SECRET_KEY` error on `runserver` | `.env` missing, or `SECRET_KEY` still `change-me` |
| Frontend says the backend is down | Django isn't running, or `NEXT_PUBLIC_API_URL` in `.env.local` is wrong |
| CORS error in the browser console | The frontend origin isn't in `CORS_ALLOWED_ORIGINS` in `backend/.env` |
| `uv: command not found` | `brew install uv` |
| `/admin/` answers 404 | `ADMIN_ENABLED` is off. It defaults to `DEBUG` (`AUTH_BLUEPRINT.md` Ch. 20) |
| Ruff fails on files you didn't touch | A new app is missing from `known-first-party` in `backend/pyproject.toml` (`TECH_DEBT` DB-14) |

---

## 3. What actually exists

**Read [`core/ARCHITECTURE.md`](core/ARCHITECTURE.md) next.** The short version — and this is worth
knowing before you plan anything:

✅ Django 5.2 + DRF · drf-spectacular OpenAPI · CORS/CSRF configured · DRF throttling ·
every endpoint denied unless it declares its permissions · Next 16 + React 19 + Tailwind 4 · a typed API wrapper · Ruff ·
a custom `users.User` (email login) · a development `docker compose` stack

Also built: RBAC and the Users module with invitations, the `core/` / `project/` split and plugins
(ADR-0010), a Vitest frontend suite, CI, Celery jobs, the settings registry, the audit engine and the
frontend app shell — the ✅/⬜ marks in [`planning/BUILD_ORDER.md`](planning/BUILD_ORDER.md) are the
exact list.

❌ **No domain models. No production Docker. No deployment.** Not built either: BUILD_ORDER 7.4–7.8, 8.5 and Phase 9.

The ❌ list is not a criticism — it is a platform, not a product. But assuming otherwise is the
fastest way to waste an afternoon. [`planning/ROADMAP.md`](planning/ROADMAP.md) has the plan.

---

## 4. The rules

**Read [`../AGENTS.md`](../AGENTS.md) in full.** It is the operating contract, it applies to humans
and AI agents alike, and it is short. The parts people get caught by:

1. **Never commit without being asked.** Every time, wait for a yes.
2. **Read a file before modifying it.**
3. **Run the verification gate before saying anything is done** — § 2 of the contract:
   ```bash
   cd backend  && uv run ruff check . && uv run ruff format --check . && uv run python manage.py check
   cd backend  && uv run pytest
   cd frontend && npm run lint && npm run typecheck
   ```
   After any model change, also `uv run python manage.py makemigrations --check --dry-run`.
   CI (`.github/workflows/ci.yml`) runs the gate on every push and PR, but run it before you push. The exact
   gate is [`AGENTS.md` § 2](../AGENTS.md); the block above omits its frontend `npm test` and script checks.
4. **Log the change** in [`DAILY_CHANGES.md`](DAILY_CHANGES.md), in the same commit as the code.
5. **Report honestly.** A failed check gets reported with its output. A green summary over a red run
   is the one unrecoverable mistake, because it destroys the value of every other report.

---

## 5. Two traps specific to this repo

**`frontend/AGENTS.md` is generated by `next dev`.** Do not hand-edit it — your changes are
overwritten, and removing it from a diff just re-creates the uncommitted change. Frontend rules go in
the root `AGENTS.md` or in
[`system-design/NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md).

**This is Next 16, not 14.** `params` and `searchParams` are `Promise`s, and caching defaults moved.
Most published advice — and most model training data — assumes 13/14 and will not compile. Next 16
ships docs at `frontend/node_modules/next/dist/docs/`; read those.

---

## 6. Your first change

1. `git branch --show-current` → should be `main`. Branch only if asked, or if the work spans sessions
2. Read [`INDEX.md`](INDEX.md) and the one **Start Here** doc for your area
3. Check [`ADR.md`](ADR.md) if you are changing the *shape* of something — an Accepted decision is
   settled
4. Check [`planning/TECH_DEBT.md`](planning/TECH_DEBT.md) before reporting a problem as new
5. Write the code, following
   [`system-design/DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) or
   [`system-design/NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md)
6. Run the gate. Log it in `DAILY_CHANGES.md`. **Then ask before committing.**
