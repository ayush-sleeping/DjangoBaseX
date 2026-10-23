# Starting a New Product From DjangoBaseX

**From an empty repo to a renamed, running product you can build on.** This is the document that
makes the boilerplate worth having — if copying it is fiddly or risky, nobody copies it.

> **Status:** built. `scripts/setup.sh` (BUILD_ORDER 4.1) does steps 1 and 6, and project identity
> (BUILD_ORDER 5.2) turns most of step 2 into setting one env key.

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

### 1. Generate a fresh `SECRET_KEY`

```bash
./scripts/setup.sh                 # Docker: Postgres + Redis + both apps
./scripts/setup.sh --no-docker     # or on the host, with SQLite
```

It writes `backend/.env` from `.env.example` and generates `SECRET_KEY`, `JWT_SIGNING_KEY`,
`MFA_ENCRYPTION_KEY` and the database and cache passwords. A re-run keeps every value it already
wrote. To make one key by hand: `cd backend && uv run python manage.py generate_secret`.

> **This one is security, not tidiness.** Django signs session cookies, password-reset tokens and
> anything using `signing` with `SECRET_KEY`. **Two products sharing a key means a session cookie
> minted by one is accepted by the other** — a cross-product authentication bypass. Never copy a
> `SECRET_KEY` between projects, and never commit one.

### 2. Rename the application

**Set `PRODUCT_NAME` (and `PRIMARY_DOMAIN`) in `backend/.env`.** Everything that spells the
product's name derives from them ([`system-design/CONFIGURATION.md`](system-design/CONFIGURATION.md)
§ 7): page titles, the sign-in page, the API title, the authenticator issuer, the from-address,
and the cookie and cache prefixes. Until you set it, the sign-in page says "Unnamed product" and
production boots warn `cfg.W003`.

> Set it **before anyone enrols in two-factor.** The issuer is written into every authenticator
> app that enrols, and correcting it means re-enrolling those users.

What is still renamed by hand:

| What | Where |
|------|-------|
| Backend package name | `[project] name` in `backend/pyproject.toml` |
| Frontend package name | `name` in `frontend/package.json` |
| README, LICENSE holder | `README.md`, `LICENSE` |
| Agent banner | `AGENTS.md` § 0 — **do this one first**, every session reads it |

### 3. Reset the inherited history

`documentation/DAILY_CHANGES.md` and `VERSION_SUMMARY.md` describe **this boilerplate's** history,
not your product's. Empty them. Keep `ADR.md` and the `adr/` records — those are decisions your
product inherits and should know about, and deleting them loses the reasoning you just took on.

### 4. Point at a real database

SQLite is a development convenience only
([ADR-0005](adr/0005-sqlite-for-dev-postgres-by-url.md)). The Docker path of `setup.sh` already
develops against PostgreSQL 16. On `--no-docker`, set `DATABASE_URL` in `backend/.env` before your
first real feature: switching later means re-testing every query against a database whose
constraint and JSON behaviour differs.

### 5. Check the two foundational questions before writing a feature

Both are in [`planning/TECH_DEBT.md`](planning/TECH_DEBT.md), both get settled by accident if nobody
settles them on purpose, and both are **much** more expensive to change later. Both are already
settled in the core:

| Decision | Why now |
|----------|---------|
| **DB-1 — session auth or JWT** | ✅ **Settled in the core** ([ADR-0009](adr/0009-jwt-in-httponly-cookies.md)): JWT in `httpOnly` cookies with DB session rows. Your frontend must share a registrable domain with the API (`SameSite=Lax`) |
| **DB-10 — custom `User` model** | ✅ **Settled in the core** ([ADR-0008](adr/0008-custom-user-model-email-identity.md)): your product inherits `users.User` with email login. Add fields to it; never swap `AUTH_USER_MODEL` |

### 6. Run it

`setup.sh` has already migrated, created the first account and printed the URLs and the
development sign-in. Day to day: `docker compose up -d --wait` and `docker compose down`. The
[README](../README.md) § Getting Started covers both paths and the by-hand steps.

Verify per [`ONBOARDING.md`](ONBOARDING.md) § 2, then run the full gate from `AGENTS.md` § 2 once
before you write anything — so you know a later failure is yours.

---

## Where your code goes

| Code | Goes in |
|------|---------|
| Product-specific | `backend/project/`, `frontend/src/project/` |
| A self-contained feature another team owns | a plugin under `backend/plugins/` (`python3 scripts/plugins.py new <name>`; the worked example is `examples/plugins/notes`) — see [`planning/PLUGIN_DEVELOPMENT.md`](planning/PLUGIN_DEVELOPMENT.md) |
| Something **every** product would want | upstream in DjangoBaseX, as a PR — not in your copy |

**That last row is the discipline that keeps updates working.** A fix made only in your copy is a
fix every other product re-discovers, and it becomes a merge conflict every time you take a core
update. If the core cannot express what you need, ask for a **seam** rather than editing core:
everyone gets it, and your copy stays mergeable.
