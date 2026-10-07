# DjangoBaseX — Operating Contract

> **This repository is a boilerplate, not a product.** It is a base that products get copied from.
> Do not give it a product identity, a client name, or domain models that belong to one product.
>
> **This is the only agent contract in this repository** ([ADR-0006](documentation/adr/0006-one-agent-contract.md)).
> Every rule lives here; `CLAUDE.md` and `GEMINI.md` import it, and `.claude/` only *enforces* and
> *points at* it ([ADR-0007](documentation/adr/0007-claude-code-harness.md)). It is always in context —
> read it in full; it is the short list you may not violate.

## 0. First response in any session

Read `CLAUDE.md` → this file before emitting any text. Then display this banner:

```text
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
[`frontend/package.json`](frontend/package.json). A version quoted from prose goes stale silently.
(In Claude Code a SessionStart hook prints the locked versions, branch and next task — still verify.)

**Know what does not exist yet:** **no authentication, no RBAC, no test suite, no CI, no Docker.**
`backend/core/models.py` has no models. If a task assumes one of those exists, check the
[Roadmap](documentation/planning/ROADMAP.md) first.

**With no specific task**, start at the lowest-numbered unfinished item in
[`BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md) — the executable backlog, with acceptance
criteria. Tasks marked **🚧 DECISION** are questions for the repository owner: ask; never answer one by
starting to code.

## 1. Non-negotiable

| # | Rule |
|---|------|
| 1 | **Never commit or push without explicit user approval.** Ask every time, and wait for a yes |
| 2 | **Never delete branches** unless asked. Branch is `main`, never `master` |
| 3 | **Read a file before you modify it.** No exceptions |
| 4 | **Ask before any destructive operation** — dropping tables, `rm -rf`, resetting migrations, `git reset --hard` |
| 5 | **Treat this repo as PUBLIC.** Anything committed here is inherited by every product copied from it, into repositories with their own access lists. Never commit real credentials, customer data, internal URLs or third-party client names. Seed/demo credentials stay obviously fake |
| 5a | **Never name another codebase.** No other project, product, repository or module name appears anywhere in this repo — docs, code, comments, commit messages, examples, agent memory. Record the *mechanism* and the *reason*, never the source. Example names are generic (`billing`, `enquiries`) |
| 6 | **Never echo `.env` *values*** into output, docs or commits — key names only |
| 7 | **Never commit** `.env`, `.env.local`, `db.sqlite3`, `.venv/`, `node_modules/`, `__pycache__/`, `.next/`, `.ruff_cache/`, `tsconfig.tsbuildinfo`, `.claude/settings.local.json` |
| 8 | **Update [`documentation/DAILY_CHANGES.md`](documentation/DAILY_CHANGES.md) in the same change as the code**, not after |
| 9 | **Report honestly.** If a check failed or a step was skipped, say so with the output. A green summary over a red run is the one unrecoverable mistake |

**Protected files — require explicit user confirmation before editing:** `AGENTS.md` (this file),
`CLAUDE.md`, `GEMINI.md`, `.env`, `.env.example`, `.gitignore`, `.editorconfig`, `LICENSE`,
`backend/config/settings.py`, `backend/pyproject.toml`, `frontend/next.config.ts`,
`frontend/tsconfig.json`, `frontend/package.json`, `.claude/settings.json`.

**Before any push:** `git status`, then `git diff --cached | grep -iE "secret|password|token|api[_-]?key"`
— and read every hit.

**`frontend/AGENTS.md` is generated** by `next dev`
(`frontend/node_modules/next/dist/server/lib/generate-agent-files.js`) — never hand-edit it; commit it
with your work. Frontend rules go here or in `documentation/system-design/NEXTJS_STANDARDS.md`.

**This is NOT the Next.js most training data knows.** Next.js 16 App Router + React 19: `params` and
`searchParams` are async, caching defaults changed. Check the installed version
(`frontend/node_modules/next/package.json`) and read the bundled guides in
`frontend/node_modules/next/dist/docs/` before writing Next.js code — not memory.

## 2. Verification gate

**Nothing is "done" until it has been run.** These are the only checks the repository has (no CI, no
test suite yet):

```bash
# Backend
cd backend && uv run ruff check .                        # lint
cd backend && uv run ruff format --check .               # format
cd backend && uv run python manage.py check              # Django system checks
cd backend && uv run python manage.py makemigrations --check --dry-run   # after ANY model change

# Frontend
cd frontend && npm run lint                              # eslint
cd frontend && npx tsc --noEmit                          # typecheck (no `typecheck` script yet — DB-2)

# Agent tooling — when .claude/hooks/ changed
python3 .claude/hooks/test_agent_guard.py
```

- **`makemigrations --check --dry-run` is not optional after a model change.** A model edited without a
  migration passes every other check, then fails on someone else's machine or on deploy.
- **`npm run build` is not in the routine gate.** It is slow and writes `.next/`, which the running dev
  server also uses. Run it deliberately, with the dev server stopped.

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

**Match the surrounding code's style. Don't introduce a second way of doing something.** Two patterns for
one job is the cost that compounds.

**Where new code goes.** A new domain is a new Django app (`backend/<app>/`), registered in
`INSTALLED_APPS`, its urls included from `config/urls.py`. `backend/core/` is for genuinely shared things.
Ask *"would a product copied from this boilerplate want it?"* — if it only serves one product, it does not
belong in this repository at all.

## 4. Working rhythm

**Before starting.** Confirm `pwd` and `git branch --show-current`. Read
[`documentation/INDEX.md`](documentation/INDEX.md), then the one **Start Here** doc for your area. Before
changing the *shape* of anything, check [`documentation/ADR.md`](documentation/ADR.md): an **Accepted**
decision is settled, and reopening it needs a new ADR, not a quiet edit. Branch only when asked or when
work spans sessions: `feature/`, `fix/`, `hotfix/`, `refactor/`, `docs/` + `<name>`.

**During.** Keep changes atomic and reviewable. Decide up front where the change gets recorded:

| Change | Recorded in |
|--------|-------------|
| Every task | an entry in `documentation/DAILY_CHANGES.md` |
| A new subsystem | a doc under `documentation/core/`, plus a row in `INDEX.md` |
| A new convention | the relevant `documentation/system-design/` file |
| A multi-session plan | a doc under `documentation/planning/` |
| A settled architectural decision | a record under `documentation/adr/`, plus a row in `ADR.md` |
| A known defect you are not fixing now | a ranked row in `documentation/planning/TECH_DEBT.md` |

**Commits** are conventional: `<type>(<scope>): <description>` — subject ≤ 72 characters, no trailing
period, blank line before the body.
Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`, `build`.
Scopes in use: `backend`, `frontend`, `api`, `auth`, `authz`, `db`, `ui`, `docs`, `infra`, `deps`,
`test`, `agents`, and app names (`core`, `users`, `employees`, `enquiries`). Stage explicit paths.

**Never add AI attribution to a commit or PR** — no `Co-Authored-By` naming a tool, no "Generated with".
Decided 2026-09-15: the commit records what changed and why; how it was produced is not part of that.

**After.** Run the § 2 gate. Update `DAILY_CHANGES.md` (and `VERSION_SUMMARY.md` for a shippable
feature) and any `core/` or `system-design/` doc whose behaviour or convention changed. Report the
verification output honestly, failures and skips included. **Then ask before committing, and wait.**

## 5. Multi-agent execution

- **Divide independent work** into packages that can proceed concurrently
- **No overlapping file ownership.** Partition on file or app boundaries and hand each worker an
  **explicit, non-overlapping file list**
- **One worker owns an atomic refactor end-to-end.** Never split one across workers
- **Migrations are never parallel.** Two agents generating migrations against one app produce a branched
  history that stays silent until `migrate` runs — on a deploy, the worst moment to find it
- **The orchestrator validates.** A subagent's "done" is a claim: read the diff and run the § 2 gate
  yourself. If a subagent's output is wrong twice, take the task over directly

## 6. Where the rest lives

| Need | File |
|------|------|
| **What this project is FOR — the tie-breaker when designs conflict** | [`documentation/VISION.md`](documentation/VISION.md) |
| **Why something is built this way — settled decisions** | [`documentation/ADR.md`](documentation/ADR.md) |
| The doc map — which single file to read | [`documentation/INDEX.md`](documentation/INDEX.md) |
| First day on this repo; running it locally | [`documentation/ONBOARDING.md`](documentation/ONBOARDING.md); [`README.md`](README.md) § Getting Started |
| What exists vs what is planned; **what to build next** | [`ROADMAP.md`](documentation/planning/ROADMAP.md); [`BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md) |
| The core + plugin architecture; the full capability map | [`CORE_ARCHITECTURE_PLAN.md`](documentation/planning/CORE_ARCHITECTURE_PLAN.md); [`PLATFORM_BLUEPRINT.md`](documentation/planning/PLATFORM_BLUEPRINT.md) |
| Starting a product from this; taking a core update | [`NEW_PROJECT.md`](documentation/NEW_PROJECT.md); [`UPGRADING.md`](documentation/UPGRADING.md) |
| Backend / frontend conventions | [`DJANGO_STANDARDS.md`](documentation/system-design/DJANGO_STANDARDS.md); [`NEXTJS_STANDARDS.md`](documentation/system-design/NEXTJS_STANDARDS.md) |
| **Designing a model** — ⚠️ 5 decisions before the first migration | [`DATA_MODEL.md`](documentation/system-design/DATA_MODEL.md); [`DATABASE_MIGRATIONS.md`](documentation/system-design/DATABASE_MIGRATIONS.md) |
| Endpoints; permissions and roles; security | [`API_DESIGN.md`](documentation/system-design/API_DESIGN.md); [`RBAC_DESIGN.md`](documentation/system-design/RBAC_DESIGN.md); [`SECURITY.md`](documentation/system-design/SECURITY.md) |
| Bugs that keep recurring — the review checklist | [`BUG_CLASSES.md`](documentation/system-design/BUG_CLASSES.md) |
| Deploying; how the two halves fit together | [`DEPLOYMENT.md`](documentation/system-design/DEPLOYMENT.md); [`core/ARCHITECTURE.md`](documentation/core/ARCHITECTURE.md) |
| Agent tooling — hooks, skills, subagents, rules | [`core/AGENT_TOOLING.md`](documentation/core/AGENT_TOOLING.md) |
| Known defects — **don't re-report as new**; what changed | [`TECH_DEBT.md`](documentation/planning/TECH_DEBT.md); [`DAILY_CHANGES.md`](documentation/DAILY_CHANGES.md) |

Planning docs are **intent, not current state** — check the code before trusting them.

## 7. Agents and tooling

| Agent | Reads | Extra |
|-------|-------|-------|
| Claude Code | `CLAUDE.md` → imports this file | `.claude/`: hooks enforce § 1/§ 4, skills hold procedures, subagents, path-scoped pointers |
| Codex, Cursor, GitHub Copilot, OpenCode | `AGENTS.md` natively | — |
| Gemini CLI | `GEMINI.md` → imports this file | — |

**Claude Code skills** (procedures that point back here): `/verify` (the § 2 gate), `/changelog`,
`/commit` (user-invoked only), `/next-task`, `/adr`, `/bug-class-check`, `/new-django-app`.
**Subagents:** `code-reviewer` and `doc-auditor` (read-only, with committed memory), `implementer` (one
spec, listed files only). The hooks *ask* before a protected file is edited and *refuse* malformed or
AI-attributed commit messages, history rewriting, and printing `.env` files. Other agents get no
enforcement — the rules above apply to them all the same.

**Never put a rule in `.claude/`, `CLAUDE.md` or `GEMINI.md`.** They point here; two contracts drift.
