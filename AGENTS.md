# DjangoBaseX — Operating Contract

> **This repository is a boilerplate, not a product.** It is the Django/Next.js sibling of
> [LaraBaseX](https://github.com/ayush-sleeping/LaraBaseX) — a base that products get copied from.
> Do not give it a product identity, a client name, or domain models that belong to one product.
>
> **This is the only agent contract in this repository.** `CLAUDE.md` imports it, and that import is
> the only thing that loads automatically. Everything below is therefore always in context. Read it
> in full; it is the short list you may not violate.

---

## 0. First response in any session

Read `CLAUDE.md` → this file before emitting any text. Then display this banner:

```
╔══════════════════════════════════════════════════════════════╗
║  📋 DjangoBaseX — AGENTS.md loaded                            ║
║  ✓ Stack: Django 5.2 + DRF  ·  Next.js 16 App Router          ║
║  ✓ Python via uv  ·  lint/format via Ruff  ·  DB: SQLite      ║
║  ✓ Branch: main (never master)                                ║
║  ✓ Docs: update documentation/DAILY_CHANGES.md every task     ║
║  ✓ Commits: ask the user first — never auto-commit            ║
╚══════════════════════════════════════════════════════════════╝
```

Then state: "Ready to work. What would you like me to work on?"

**Never describe the stack from memory.** Read [`backend/pyproject.toml`](backend/pyproject.toml) and
[`frontend/package.json`](frontend/package.json). A version quoted from prose goes stale silently and
is how a README ends up wrong in a dozen places.

**Know what does not exist yet.** As of the current scaffold there is **no authentication, no RBAC,
no test suite, no CI and no Docker setup.** `backend/core/tests.py` is Django's empty stub and
`backend/core/models.py` has no models. If a task assumes one of those exists, check first — the
[Roadmap](documentation/planning/ROADMAP.md) says what is real and what is planned.

**If you have been handed this project with no specific task**, read
[`documentation/planning/BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md) and start at the
lowest-numbered unfinished item. It is the executable backlog, in dependency order, with acceptance
criteria per task. **Two of its tasks are marked 🚧 DECISION** — those are questions for the
repository owner, not work for you. Ask; do not answer them by starting to code.

---

## 1. Non-negotiable

| # | Rule |
|---|------|
| 1 | **Never commit or push without explicit user approval.** Ask every time, and wait for a yes |
| 2 | **Never delete branches** unless asked. Branch is `main`, never `master` |
| 3 | **Read a file before you modify it.** No exceptions |
| 4 | **Ask before any destructive operation** — dropping tables, `rm -rf`, resetting migrations, `git reset --hard` |
| 5 | **Treat this repo as PUBLIC.** It is a boilerplate: anything committed here is inherited by every product copied from it, into repositories with their own access lists, long after anyone remembers where the value came from. Never commit real credentials, customer data, internal URLs or third-party client names. Seed/demo credentials stay obviously fake |
| 6 | **Never echo `.env` *values*** into output, docs or commits — key names only |
| 7 | **Never commit** `.env`, `.env.local`, `db.sqlite3`, `.venv/`, `node_modules/`, `__pycache__/`, `.next/`, `.ruff_cache/`, `tsconfig.tsbuildinfo` |
| 8 | **Update [`documentation/DAILY_CHANGES.md`](documentation/DAILY_CHANGES.md) in the same change as the code**, not after |
| 9 | **Report honestly.** If a check failed or a step was skipped, say so with the output. A green summary over a red run is the one unrecoverable mistake |

**Protected files — require explicit user confirmation before editing:** `AGENTS.md` (this file),
`CLAUDE.md`, `.env`, `.env.example`, `.gitignore`, `.editorconfig`, `LICENSE`,
`backend/config/settings.py`, `backend/pyproject.toml`, `frontend/next.config.ts`,
`frontend/tsconfig.json`, `frontend/package.json`.

**Before any push:** `git status`, then
`git diff --cached | grep -iE "secret|password|token|api[_-]?key"`.

### ⚠️ `frontend/AGENTS.md` is generated — do not hand-edit it

`next dev` writes and re-adds that file (see
`frontend/node_modules/next/dist/server/lib/generate-agent-files.js`). Removing it from a diff only
re-creates the uncommitted change. Commit it with your work to keep the tree clean, and put your own
frontend rules in **this** file or in `documentation/system-design/NEXTJS_STANDARDS.md` instead —
anything written into the generated file is lost on the next `next dev`.

### ⚠️ This is NOT the Next.js most training data knows

**Installed: Next.js 16.3.4, App Router, React 19.2.8.** Much published advice assumes 13/14 and
**does not apply here** — `params` and `searchParams` are async, caching defaults changed, and the
App Router conventions moved. Verify against the installed tree before writing Next.js code:

```bash
node -e "console.log(require('./frontend/node_modules/next/package.json').version)"
```

Next 16 ships bundled agent docs at `frontend/node_modules/next/dist/docs/` — read the relevant guide
there rather than from memory.

---

## 2. Verification gate

**Nothing is "done" until it has been run.** Use these exact commands — they are the only checks this
repository currently has, because there is no CI and no test suite yet:

```bash
# Backend
cd backend && uv run ruff check .                        # lint
cd backend && uv run ruff format --check .               # format
cd backend && uv run python manage.py check              # Django system checks
cd backend && uv run python manage.py makemigrations --check --dry-run   # after ANY model change

# Frontend
cd frontend && npm run lint                              # eslint
cd frontend && npx tsc --noEmit                          # typecheck
```

⚠️ **There is no `typecheck` npm script yet** — `npx tsc --noEmit` is the gate until one is added
(tracked in [`TECH_DEBT.md`](documentation/planning/TECH_DEBT.md) as **DB-2**).

⚠️ **`npm run build` is not part of the routine gate.** It is slow and it writes `.next/`, which the
running dev server is also using. Run it deliberately, with the dev server stopped, when you have
changed something that only a production build exercises.

⚠️ **`makemigrations --check --dry-run` is not optional after a model change.** A model edited
without a migration passes every check above and then fails on someone else's machine, or on deploy.

---

## 3. Layer boundaries

| Layer | Rule |
|-------|------|
| DRF views (`views.py`) | Thin — HTTP concerns only: parse, authorize, delegate, respond |
| Business logic | A `services.py` module in the app, never a view and never a serializer |
| Serializers | Shape and validate data. No queries, no side effects, no business rules |
| Models | Field definitions, constraints, `Meta`, and simple derived properties only |
| Querysets | Custom `Manager`/`QuerySet` methods on the model — not repeated `.filter()` chains in views |
| Settings | Every environment-dependent value comes from `.env` via `django-environ`. Never hard-code a host, key or URL in `settings.py` |
| Frontend data | Through `src/lib/api.ts`. **Never `fetch()` inline in a component** |
| Business logic (frontend) | Never in a page or component — put it in `src/lib/` |

**Match the surrounding code's style. Don't introduce a second way of doing something.** Two
patterns for the same job is the cost that compounds; the reader has to learn both and then guess
which one is current.

**Where new code goes.** A new domain is a new Django app (`backend/<app>/`), registered in
`INSTALLED_APPS` with its urls included from `config/urls.py`. `backend/core/` is for genuinely
shared things — the health probe, base classes, shared utilities. Decide by asking *"would a product
copied from this boilerplate want it?"* If yes it is core or a reusable app; if it only serves one
product, it does not belong in this repository at all.

---

## 4. Working rhythm

**Before starting.** Confirm the working directory (`pwd`) and the branch
(`git branch --show-current`). Read [`documentation/INDEX.md`](documentation/INDEX.md), then the one
**Start Here** doc for your area — § 6 below is the map. Before changing the *shape* of anything,
check [`documentation/ADR.md`](documentation/ADR.md): a decision listed there as **Accepted** is
settled, and reopening it needs a new ADR rather than a quiet edit.

Branch only when asked, or when work spans sessions. If you do: `feature/<name>`, `fix/<name>`,
`hotfix/<name>`, `refactor/<name>`, `docs/<name>`.

**During.** Keep changes atomic and reviewable. Decide up front where the change gets recorded:

| Change | Recorded in |
|--------|-------------|
| Every task | an entry in `documentation/DAILY_CHANGES.md` |
| A new subsystem | a doc under `documentation/core/`, plus a row in `INDEX.md` |
| A new convention | the relevant `documentation/system-design/` file |
| A multi-session plan | a doc under `documentation/planning/` |
| A settled architectural decision | a record under `documentation/adr/`, plus a row in `ADR.md` |
| A known defect you are not fixing now | a ranked row in `documentation/planning/TECH_DEBT.md` |

**Commits** are conventional: `<type>(<scope>): <description>`.
Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`, `build`.
Scopes in use: `backend`, `frontend`, `api`, `auth`, `authz`, `db`, `ui`, `docs`, `infra`, `deps`,
`test`, and app names (`core`, `users`, `employees`, `enquiries`).

**Never add AI attribution to a commit message** — no `Co-Authored-By`, no "Generated with", no
tool name in the body. Decided 2026-09-15. The commit records what changed and why; how it was
produced is not part of that, and a trailer naming a tool ages badly in a history that outlives the
tool. Same rule as the upstream core this contract was adapted from.

**After.** Run the § 2 gate. Update `DAILY_CHANGES.md`, and `VERSION_SUMMARY.md` if the work is a
shippable feature. Update the affected `core/` or `system-design/` doc if behaviour or a convention
changed. Report the verification output honestly — including failures and anything skipped. **Then
ask before committing, and wait.**

---

## 5. Multi-agent execution

- **Divide independent work** into packages that can proceed concurrently
- **No overlapping file ownership.** Two workers must never hold the same file. Partition on file or
  app boundaries and hand each worker an **explicit, non-overlapping file list**
- **One worker owns an atomic refactor end-to-end.** Never split one across workers
- **Migrations are never parallel.** Two agents generating migrations against the same app produce a
  branched history, which is silent until `migrate` runs — on a deploy, the worst moment to find it
- **The orchestrator validates.** Never accept a subagent's "done" without running the § 2 gate
  yourself. If a subagent's output is wrong twice, take the task over directly

---

## 6. Where the rest lives

| Need | File |
|------|------|
| **What this project is FOR — the tie-breaker when designs conflict** | [`documentation/VISION.md`](documentation/VISION.md) |
| **Why something is built this way — settled decisions** | [`documentation/ADR.md`](documentation/ADR.md) |
| The doc map — which single file to read | [`documentation/INDEX.md`](documentation/INDEX.md) |
| First day on this repo, end to end | [`documentation/ONBOARDING.md`](documentation/ONBOARDING.md) |
| Running it locally | [`README.md`](README.md) § Getting Started |
| What actually exists vs what is planned | [`documentation/planning/ROADMAP.md`](documentation/planning/ROADMAP.md) |
| **What to build next, with acceptance criteria** | [`documentation/planning/BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md) |
| The core + plugin architecture | [`documentation/planning/CORE_ARCHITECTURE_PLAN.md`](documentation/planning/CORE_ARCHITECTURE_PLAN.md) |
| Starting a new product from this | [`documentation/NEW_PROJECT.md`](documentation/NEW_PROJECT.md) |
| Taking a core update into a product | [`documentation/UPGRADING.md`](documentation/UPGRADING.md) |
| Backend conventions | [`documentation/system-design/DJANGO_STANDARDS.md`](documentation/system-design/DJANGO_STANDARDS.md) |
| Frontend conventions | [`documentation/system-design/NEXTJS_STANDARDS.md`](documentation/system-design/NEXTJS_STANDARDS.md) |
| **Designing a model** — ⚠️ 5 decisions before the first migration | [`documentation/system-design/DATA_MODEL.md`](documentation/system-design/DATA_MODEL.md) |
| Adding an endpoint | [`documentation/system-design/API_DESIGN.md`](documentation/system-design/API_DESIGN.md) |
| Permissions and roles | [`documentation/system-design/RBAC_DESIGN.md`](documentation/system-design/RBAC_DESIGN.md) |
| Anything security-sensitive | [`documentation/system-design/SECURITY.md`](documentation/system-design/SECURITY.md) |
| Schema changes | [`documentation/system-design/DATABASE_MIGRATIONS.md`](documentation/system-design/DATABASE_MIGRATIONS.md) |
| Deploying | [`documentation/system-design/DEPLOYMENT.md`](documentation/system-design/DEPLOYMENT.md) |
| How the two halves fit together | [`documentation/core/ARCHITECTURE.md`](documentation/core/ARCHITECTURE.md) |
| Known defects — **don't re-report as new** | [`documentation/planning/TECH_DEBT.md`](documentation/planning/TECH_DEBT.md) |
| What changed, and when | [`documentation/DAILY_CHANGES.md`](documentation/DAILY_CHANGES.md) |

Planning docs are **intent, not current state** — check the code before trusting them.

---

## 7. Which file each agent reads

| Agent | Entry point | Note |
|-------|-------------|------|
| Claude Code | `CLAUDE.md` | Loaded automatically; imports this file |
| OpenAI Codex / OpenCode | `AGENTS.md` (root) | Reads this file directly |
| Gemini CLI | `GEMINI.md` | Not present — falls back to this file |
| GitHub Copilot | `.github/copilot-instructions.md` | Not present |
| Cursor | `.cursor/rules/*.mdc` | Not present |

Subdirectory `AGENTS.md` files are **never auto-discovered** — only `CLAUDE.md` files are. That is
why `frontend/AGENTS.md` only loads via `frontend/CLAUDE.md`, and why the rules that matter live
here rather than there.
