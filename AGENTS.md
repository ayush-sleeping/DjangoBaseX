# DjangoBaseX — Operating Contract

> **This repository is a boilerplate, not a product.** It is a base that products get copied from.
> Do not give it a product identity, a client name, or domain models that belong to one product.
>
> **This is the only agent contract in this repository** ([ADR-0006](documentation/adr/0006-one-agent-contract.md)).
> Every rule lives here; `CLAUDE.md` and `GEMINI.md` import it, and `.claude/` only *enforces* and
> *points at* it ([ADR-0007](documentation/adr/0007-claude-code-harness.md)). It is a map: detail is one hop away.

## 0. Follow the protocol

At session start, and whenever the owner says "follow the protocol" (any wording), in order, before any other text:

1. Read `CLAUDE.md` → this file → [`documentation/PURPOSE.md`](documentation/PURPOSE.md) (why this exists; the
   tie-breaker) → [`documentation/INVARIANTS.md`](documentation/INVARIANTS.md) (what no change may break).
2. Read the docs for the task (**Need → read** below) and the [`ADR.md`](documentation/ADR.md) row for anything you
   will change the shape of.
3. Verify state, never memory: `pwd`, `git branch --show-current`, `git status --short`, `git worktree list`.
4. Display the banner, then: "Ready to work on DjangoBaseX. What would you like me to work on?"

```text
╔══════════════════════════════════════════════════════════════╗
║  📋 DjangoBaseX — AGENTS.md loaded                            ║
║  ✓ Stack: Django 5.2 + DRF  ·  Next.js 16 App Router          ║
║  ✓ Python via uv  ·  Ruff  ·  SQLite local, PostgreSQL in CI  ║
║  ✓ Branch: main (never master)                                ║
║  ✓ Docs: update documentation/DAILY_CHANGES.md every task     ║
║  ✓ Commits: ask the user first — never auto-commit            ║
╚══════════════════════════════════════════════════════════════╝
```

| Need | Read first (`documentation/`) | Then |
|---|---|---|
| Bug report / something broken | [`PRODUCTION.md`](documentation/PRODUCTION.md), [`system-design/TRAPS.md`](documentation/system-design/TRAPS.md) | [`DOMAIN.md`](documentation/DOMAIN.md) flow, [`TESTING.md`](documentation/TESTING.md) (failing test first) |
| A `BUILD_ORDER.md` task or new feature | [`PURPOSE.md`](documentation/PURPOSE.md), [`DOMAIN.md`](documentation/DOMAIN.md) | [`ARCHITECTURE.md`](documentation/ARCHITECTURE.md) recipe, the task's spec in `system-design/` |
| Backend change | [`CODE_STANDARDS.md`](documentation/CODE_STANDARDS.md) | [`ARCHITECTURE.md`](documentation/ARCHITECTURE.md), [`SECURITY.md`](documentation/SECURITY.md) |
| UI change | [`UI_STANDARDS.md`](documentation/UI_STANDARDS.md) | its gold-standard page |
| Model / migration | [`system-design/DATA_MODEL.md`](documentation/system-design/DATA_MODEL.md) (5 decisions first) | [`DATABASE_MIGRATIONS.md`](documentation/system-design/DATABASE_MIGRATIONS.md) |
| Auth, permissions, secrets | [`SECURITY.md`](documentation/SECURITY.md) | `AUTH_BLUEPRINT.md`, `RBAC_DESIGN.md` |
| Releasing the core | [`RELEASE.md`](documentation/RELEASE.md) | [`UPGRADING.md`](documentation/UPGRADING.md) |
| Before saying "done" | [`DEFINITION_OF_DONE.md`](documentation/DEFINITION_OF_DONE.md) | — |

**Never describe the stack from memory.** Read [`backend/pyproject.toml`](backend/pyproject.toml) and
[`frontend/package.json`](frontend/package.json). (In Claude Code a SessionStart hook prints the locked versions,
branch and next task — still verify.)

**Know what exists.** Built (BUILD_ORDER ✅): auth (ADR-0009), RBAC, Users (the reference module to copy), the
`project/` split (ADR-0010), plugins (`scripts/plugins.py`, example `examples/plugins/notes`), the typed settings
registry, flags, lookups, identity, request id + scrubber, health rungs, `doctor`, encryption, audit, money, Celery
jobs, outbox + reconcilers + locks, the retention engine (`core/retention/`), safe outbound HTTP + the non-production guard (`core/http/`, `core/mail/`), the
frontend platform (data layer, shell, design system, i18n, per-request nonce CSP, runtime brand colours), dev Docker
Compose, the doc-link test and `manage.py seed_demo` (9.6), webhooks outbound + inbound and the events registry
(`core/webhooks/`, 7.6), notifications (`core/notifications/`, `core/mail/render.py`, 7.7), ops alerting
(`core/ops/`, 7.8), plugin soft-disable + the `core.sdk` facade (9.1; plugins import only `core.sdk`), the API platform
(machine-caller tokens per ADR-0016, list pipeline, error catalogue, sniffed uploads; `core/api_tokens/`, 9.2), static
security headers + `/fe/revalidate` (8.5b, part), operations (`scripts/deploy.py`, `manage.py backup`/`restore`, the
setup API, `Dockerfile.prod` images — written, not yet proven on a real host; 9.5), data lifecycle (scoping registry
with write-path narrowing via `BaseViewSet.scope()`, soft delete + recycle bin, state history, provenance;
`core/lifecycle/`, 9.3), domain primitives (document numbering, state machine, business calendar, bulk actions,
import/export; 9.4). **Not built:** 8.5b's backend revalidate caller, logos and per-tenant identity (DB-90–92), 10.1;
Sentry wiring (ADR-0013). Check
[`ROADMAP.md`](documentation/planning/ROADMAP.md) / [`BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md) before assuming.

**With no specific task**, start at the lowest-numbered unfinished item in `BUILD_ORDER.md` — the executable
backlog, with acceptance criteria. Tasks marked **🚧 DECISION** are questions for the repository owner: ask; never
answer one by starting to code.

## 1. Non-negotiable

| # | Rule |
|---|------|
| 1 | **Never commit or push without explicit user approval.** Ask every time, and wait for a yes |
| 2 | **Never delete branches** unless asked. Branch is `main`, never `master` |
| 3 | **Read a file before you modify it.** No exceptions |
| 4 | **Ask before any destructive operation** — dropping tables, `rm -rf`, resetting migrations, `git reset --hard` |
| 5 | **Treat this repo as PUBLIC.** Anything committed here is inherited by every product copied from it. Never commit real credentials, customer data, internal URLs or third-party client names. Seed/demo credentials stay obviously fake |
| 5a | **Never name another codebase.** No other project, product, repository, company or module name appears anywhere in this repo — docs, code, comments, commit messages, examples, agent memory. Record the *mechanism* and the *reason*, never the source. Example names are generic (`billing`, `enquiries`) |
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

**`frontend/AGENTS.md` is generated** by `next dev` — never hand-edit it; commit it with your work. Frontend rules
go here or in `documentation/system-design/NEXTJS_STANDARDS.md`.

**This is NOT the Next.js most training data knows.** Next.js 16 App Router + React 19: `params` and
`searchParams` are async, caching defaults changed. Check `frontend/node_modules/next/package.json` and read
`frontend/node_modules/next/dist/docs/` before writing Next.js code — not memory.

## 2. Verification gate

**Nothing is "done" until it has been run.** CI (`.github/workflows/ci.yml`) runs exactly these on every push and
PR, on PostgreSQL 16 — run them first anyway. Detail, per-change test rules and what SQLite cannot prove:
[`TESTING.md`](documentation/TESTING.md).

```bash
# Backend
cd backend && uv run ruff check .                        # lint
cd backend && uv run ruff format --check .               # format
cd backend && uv run python manage.py check              # Django system checks
cd backend && uv run python manage.py makemigrations --check --dry-run   # after ANY model change
cd backend && uv run pytest                              # tests (in-memory DB/cache/email — safe anytime)
cd backend && uv run ruff check --config pyproject.toml ../scripts ../examples   # + format --check

# Frontend
cd frontend && npm run lint                              # eslint
cd frontend && npm run typecheck                         # next typegen && tsc --noEmit
cd frontend && npm test                                  # vitest

python3 .claude/hooks/test_agent_guard.py                # agent tooling — when .claude/hooks/ changed
```

- **`makemigrations --check --dry-run` is not optional after a model change.**
- **`npm run build` is not in the routine gate.** It is slow and writes `.next/`, which the running dev server
  also uses. Run it deliberately, with the dev server stopped.
- Run each command separately and trust exit codes, not printed text.

## 3. Layer boundaries

Views are thin (parse, authorize, delegate, respond) · business logic in the app's `services.py` · serializers
shape and validate only · models hold fields, constraints and `Meta` · querysets as custom `Manager`/`QuerySet`
methods · every environment value from `.env` via `django-environ`, never hard-coded in `settings.py` · frontend
data only through `src/core/lib/api.ts`, never `fetch()` in a component · frontend logic in `src/core/lib/`
(product code: `src/project/`). The table with gold-standard files: [`ARCHITECTURE.md`](documentation/ARCHITECTURE.md)
§ Layers; rules and checks: [`CODE_STANDARDS.md`](documentation/CODE_STANDARDS.md).

**Match the surrounding code's style. Don't introduce a second way of doing something.**

**Where new code goes.** A new domain is a new Django app (`backend/<app>/`), registered in `INSTALLED_APPS`, its
urls included from `config/urls.py`. Ask *"would a product copied from this boilerplate want it?"* — if it only
serves one product, it belongs in `project/` or a plugin, not the core. Recipes: `ARCHITECTURE.md` § How to add.

## 4. Working rhythm

**Before.** § 0. Define done in one to three lines and the command that proves it. Blast radius: `rg -l "<name>"`
before changing a function, route, column or setting key; `git log -5 --oneline -- <file>` and read recent fixes.
An **Accepted** ADR is settled — reopening it needs a new ADR. Branch only when asked or when work spans sessions:
`feature/`, `fix/`, `hotfix/`, `refactor/`, `docs/` + `<name>`.

**During.** Smallest coherent change; mirror the nearest gold-standard file. A bug fix starts with a failing test.
Same approach failed twice → stop and rethink or ask; never a third variation. Record the change:

| Change | Recorded in |
|--------|-------------|
| Every task | an entry in `documentation/DAILY_CHANGES.md` |
| A new subsystem | a doc under `documentation/core/`, plus a row in `INDEX.md` |
| A new convention | the relevant `documentation/system-design/` file |
| A multi-session plan | a doc under `documentation/planning/` |
| A settled architectural decision | a record under `documentation/adr/`, plus a row in `ADR.md` |
| A known defect you are not fixing now | a ranked row in `documentation/planning/TECH_DEBT.md` |
| Something that cost time and will bite again | a row in `documentation/system-design/TRAPS.md` |

**Commits** are conventional: `<type>(<scope>): <description>` — subject ≤ 72 characters, no trailing period,
blank line before the body. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`, `build`.
Scopes: `backend`, `frontend`, `api`, `auth`, `authz`, `db`, `ui`, `docs`, `infra`, `deps`, `test`, `agents`, and
app names (`core`, `users`, …). Stage explicit paths. **Never add AI attribution to a commit or PR** (decided
2026-09-15).

**After.** Run the § 2 gate. Score the work against [`DEFINITION_OF_DONE.md`](documentation/DEFINITION_OF_DONE.md)
with evidence labels (*observed* · *derived* · *inferred* · *unknown*). Update `DAILY_CHANGES.md` (and
`VERSION_SUMMARY.md` for a shippable feature) and any doc whose behaviour or convention changed. **Then ask before
committing, and wait.**

## 5. Multi-agent execution

- **Divide independent work** into packages with an **explicit, non-overlapping file list** each
- **One worker owns an atomic refactor end-to-end.** Never split one across workers
- **Migrations are never parallel** — two agents generating migrations against one app branch the history silently
- **The orchestrator validates.** A subagent's "done" is a claim: read the diff and run the § 2 gate yourself. Wrong
  twice → take the task over. Detail: [`core/AGENT_TOOLING.md`](documentation/core/AGENT_TOOLING.md)

## 6. Where the rest lives

[`documentation/INDEX.md`](documentation/INDEX.md) is the doc map — one row per task, read the one file you need.
Settled decisions: [`ADR.md`](documentation/ADR.md). First day: [`ONBOARDING.md`](documentation/ONBOARDING.md).
Starting a product: [`NEW_PROJECT.md`](documentation/NEW_PROJECT.md). Known defects — **don't re-report as new**:
[`TECH_DEBT.md`](documentation/planning/TECH_DEBT.md). Recurring bug classes: [`BUG_CLASSES.md`](documentation/system-design/BUG_CLASSES.md).

Planning docs (`documentation/planning/`) are **intent, not current state** — check the code before trusting them.
When a doc and the code disagree, the code is current and the doc is the bug — unless an Accepted ADR says
otherwise; then the code drifted.

## 7. Agents and tooling

| Agent | Reads | Extra |
|-------|-------|-------|
| Claude Code | `CLAUDE.md` → imports this file | `.claude/`: hooks enforce § 1/§ 4, skills hold procedures, subagents, path-scoped pointers |
| Codex, Cursor, GitHub Copilot, OpenCode | `AGENTS.md` natively | — |
| Gemini CLI | `GEMINI.md` → imports this file | — |

**Claude Code skills:** `/verify` (the § 2 gate), `/changelog`, `/commit` (user-invoked only), `/next-task`, `/adr`,
`/bug-class-check`, `/new-django-app`. **Subagents:** `code-reviewer` and `doc-auditor` (read-only, with committed
memory), `implementer` (one spec, listed files only). The hooks *ask* before a protected file is edited and *refuse*
malformed or AI-attributed commit messages, history rewriting, and printing `.env` files. Other agents get no
enforcement — the rules above apply to them all the same.

**Never put a rule in `.claude/`, `CLAUDE.md` or `GEMINI.md`.** They point here; two contracts drift.
