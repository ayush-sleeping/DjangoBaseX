# Testing Strategy

**There are zero tests today.** `backend/core/tests.py` is Django's stub and the frontend has no
runner installed. Nothing in this repository can fail a build.

**Status:** plan. Resolves [`TECH_DEBT.md`](TECH_DEBT.md) DB-5 and DB-6.

---

## Why this is the highest-leverage thing to build next

Everything that makes the two reference projects trustworthy is a **test**, not a convention:

| Guarantee | What enforces it in the source project |
|-----------|----------------------------------------|
| Core does not depend on the product | `backend/tests/core/test_core_extraction.py` |
| Frontend core does not import product code | `frontend/tests/boundaries.test.ts` |
| Every gated route actually refuses anonymous callers | `test_route_enforcement.py` — walks the app's **own route table**, so a route added next week is covered the moment it exists |
| No plugin imports another plugin | PriorCoreB verifies by grep; we automate it |

`PriorCoreD` records the cost of not having them: `npm run build` was broken by a type
error and **stayed broken, unnoticed**, because nothing ran it. Its frontend once had 48,000 lines
across 72 routes and 171 components with **zero tests**, against 38,000 backend lines with 1,130.

**And the timing argument:** every module added before the suite exists is a module whose tests get
written later — and "later" has a known success rate. The suite is a few hours of work at this size
and gets more expensive with every feature.

---

## The stack

| Layer | Tool | Why |
|-------|------|-----|
| Backend | **pytest + pytest-django** | Better fixtures and parametrisation than `unittest`; the Django plugin gives `db`, `client`, `settings` |
| Fixtures | **factory_boy** | Hand-built model setup is where test suites rot |
| Coverage | **pytest-cov** | For the floor, below |
| Frontend | **Vitest** | Fast, works with the TS config already present |
| Components | **@testing-library/react** | Tests behaviour, not implementation |

---

## The four tests that matter most

Write these **before** feature tests. They are cheap, they never go stale, and each one enforces a
rule that is otherwise only written down.

1. **Architecture boundaries** — AST-scan imports: `core/` must not import `project` or any plugin;
   no plugin may import another. This is what makes the core genuinely extractable
2. **Route enforcement** — ask Django's resolver for **every** URL, call each unauthenticated, fail on
   anything that is not 401/403. Steal the source project's refinement: **a 404 counts as a failure
   too**, because it means the handler ran a lookup before checking who was asking
3. **Migrations** — one head per app, and every model has a table. A branched chain is silent until
   `migrate` runs, which on a deploy is the worst moment to find it
4. **Plugin conventions** — every plugin has `plugin.toml`, an explicit `app_label`, and the four
   required prefixes

**Why these first:** a feature test proves one feature works. These four prove a *class* of mistake
cannot be merged, including mistakes nobody has made yet.

---

## Coverage floors, not targets

Adopted from `PriorCoreD`, including the reasoning:

> A floor, not a target — set to **where the code actually is**, because a floor above reality fails
> on arrival and gets deleted, which is how a coverage gate becomes decoration.

Two gates, because one is not enough:

- **A global floor** (`--cov-fail-under`). Its job is to stop a *regression*: a large untested module
  pulls the total down and fails the build, which is the moment somebody would otherwise ship it
- **Per-file floors.** The global floor cannot see a single untested module — a new 300-line service
  at 20% costs a project at 70% about two points and the build stays green

Raise the floor deliberately after covering something. Never set it aspirationally.

---

## CI

One workflow, **two jobs** — backend and frontend separately, so a Python failure still reports the
TypeScript result. One job stops at the first error and hides half the picture on every red build.

```
backend:   ruff check · ruff format --check · manage.py check
           makemigrations --check --dry-run · pytest · coverage floor
frontend:  npm ci · eslint · tsc --noEmit · vitest · next build
```

`next build` belongs **in CI**, not the local gate — it is the check that was silently broken in the
source project precisely because nothing ran it.

**Run CI against PostgreSQL 16**, not SQLite. A suite proving behaviour against a database nobody
deploys proves it in the wrong place ([ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)).

### No `continue-on-error`

The source project's lint step carried one for months with a note to remove it. The note it left
behind is the lesson: **a non-blocking check is a check nobody reads.** Either a check blocks, or
delete it.

---

## Order of work

1. `pytest` + `pytest-django` + `factory_boy` installed, one smoke test green
2. The four architecture tests above
3. CI workflow running the whole gate on every PR
4. Coverage floors, set to measured reality
5. Frontend Vitest + the boundary test
6. Feature tests from here on, written **with** the feature
