# Starting a New Product From DjangoBaseX

**From an empty repo to a renamed, running product you can build on.** This is the document that
makes the boilerplate worth having — if copying it is fiddly or risky, nobody copies it.

> **Status:** the *procedure* is settled; some steps are manual until Phase 0 of
> [`planning/CORE_ARCHITECTURE_PLAN.md`](planning/CORE_ARCHITECTURE_PLAN.md) lands `scripts/setup.sh`.
> Steps that a script will do later are marked 🔜.

---

## ⚠️ Do not press "Use this template"

A GitHub template repository **shares no git history** with the repos made from it. A product created
that way can never take a core update: `git merge core/main` has no common ancestor and simply
refuses.

**Clone and re-origin instead.** This is the single most important instruction on this page.

```bash
git clone https://github.com/ayush-sleeping/DjangoBaseX.git my-product
cd my-product

gh repo create <owner>/my-product --private        # or create it in the UI
git remote rename origin core                      # upstream — this is how updates arrive
git remote add origin git@github.com:<owner>/my-product.git
git push -u origin main
```

You now have two remotes, and that is deliberate:

| Remote | Points at | Used for |
|--------|-----------|----------|
| `origin` | your product | everyday work |
| `core` | DjangoBaseX | `git fetch core && git merge core/main` — see [`UPGRADING.md`](UPGRADING.md) |

### Copying a local directory instead

Works, but **delete the git history and the database**, then re-point the remotes:

```bash
cp -r DjangoBaseX my-product && cd my-product
rm -rf .git backend/db.sqlite3 backend/.env frontend/.env.local
git init && git branch -m main
```

> ⚠️ `backend/db.sqlite3` and the `.env` files are gitignored, so a **clone** never carries them —
> but `cp -r` does. Inheriting them means starting with another product's rows and another product's
> `SECRET_KEY`. You then get no upstream remote either, which costs you core updates permanently.
> **Prefer the clone.**

---

## The rename checklist

Nothing below is optional. Work top to bottom.

### 1. Generate a fresh `SECRET_KEY` 🔜

```bash
cd backend && cp .env.example .env
uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
# paste into SECRET_KEY in backend/.env
```

> **This one is security, not tidiness.** Django signs session cookies, password-reset tokens and
> anything using `signing` with `SECRET_KEY`. **Two products sharing a key means a session cookie
> minted by one is accepted by the other** — a cross-product authentication bypass. Never copy a
> `SECRET_KEY` between projects, and never commit one.

### 2. Rename the application

| What | Where |
|------|-------|
| API title and description | `SPECTACULAR_SETTINGS` in `backend/config/settings.py` |
| Backend package name | `[project] name` in `backend/pyproject.toml` |
| Frontend package name | `name` in `frontend/package.json` |
| Page title / metadata | `frontend/src/app/layout.tsx` |
| README, LICENSE holder | `README.md`, `LICENSE` |
| Agent banner | `AGENTS.md` § 0 — **do this one first**, every session reads it |

### 3. Reset the inherited history

`documentation/DAILY_CHANGES.md` and `VERSION_SUMMARY.md` describe **this boilerplate's** history,
not your product's. Empty them. Keep `ADR.md` and the `adr/` records — those are decisions your
product inherits and should know about, and deleting them loses the reasoning you just took on.

### 4. Point at a real database

SQLite is a development convenience only
([ADR-0005](adr/0005-sqlite-for-dev-postgres-by-url.md)). Set `DATABASE_URL` in `backend/.env`
before your first real feature — switching later means re-testing every query against a database
whose constraint and JSON behaviour differs.

### 5. Decide the two open questions before writing a feature

Both are in [`planning/TECH_DEBT.md`](planning/TECH_DEBT.md), both get settled by accident if nobody
settles them on purpose, and both are **much** more expensive to change later:

| Decision | Why now |
|----------|---------|
| **DB-1 — session auth or JWT** | Whichever your first authenticated endpoint uses settles it. Different CSRF, CORS and refresh models |
| **DB-10 — custom `User` model** | Must land **before** the first migration referencing `AUTH_USER_MODEL`. Swapping it afterwards is one of Django's genuinely painful migrations — even if the answer is "the default is fine", answer it |

### 6. Run it

```bash
cd backend  && uv sync && uv run python manage.py migrate && uv run python manage.py createsuperuser
cd frontend && npm install && cp .env.example .env.local
```

Verify per [`ONBOARDING.md`](ONBOARDING.md) § 2, then run the full gate from `AGENTS.md` § 2 once
before you write anything — so you know a later failure is yours.

---

## Where your code goes

| Code | Goes in |
|------|---------|
| Product-specific | `backend/project/`, `frontend/src/project/` 🔜 |
| A self-contained feature another team owns | its own plugin repo 🔜 — see [`planning/PLUGIN_DEVELOPMENT.md`](planning/PLUGIN_DEVELOPMENT.md) |
| Something **every** product would want | upstream in DjangoBaseX, as a PR — not in your copy |

**That last row is the discipline that keeps updates working.** A fix made only in your copy is a
fix every other product re-discovers, and it becomes a merge conflict every time you take a core
update. If the core cannot express what you need, ask for a **seam** rather than editing core:
everyone gets it, and your copy stays mergeable.
