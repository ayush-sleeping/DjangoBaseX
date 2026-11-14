# Docs plan — the agent-ready documentation set

> **Status:** Done — 2026-11-14 · branch `docs/agent-docs`

**Goal.** An agent (or a developer) arriving cold can take a bug report or a `BUILD_ORDER.md` task and deliver it
correctly in every dimension — purpose, design, code, UI, tests, security, operations — without asking where things
are or what "good" means here. **Done when** every file below exists, is indexed, every relative link resolves,
and a fresh agent given one past bug and one small feature using only the docs needs no doc it cannot find.

## Decisions (2026-11-14, repository owner)

| # | Decision |
|---|---|
| 1 | `VISION.md` is renamed `PURPOSE.md` — one source of truth; links repointed (history in `DAILY_CHANGES.md` left as written) |
| 2 | `PRODUCTION.md` = diagnosing a running instance; DjangoBaseX has no deployment of its own |
| 3 | Links are checked with a local one-off script now; the CI doc-link test stays with BUILD_ORDER 9.6 |
| 4 | Docs land before 7.4 and 8.5; those branches are brought up to date afterwards |
| 5 | The traps table lives in `system-design/TRAPS.md`; `.claude/rules/` files point at it (ADR-0007) |
| 6 | `planning/TESTING_STRATEGY.md` is replaced by `TESTING.md` (tests now exist — reality, not intent) |

## The set — `documentation/`

| File | Kind | Phase |
|---|---|---|
| `PURPOSE.md` | why it exists, priorities, non-goals (was `VISION.md`) | 1 ✅ |
| `INVARIANTS.md` | hard rules, each with source + enforcing test | 1 ✅ |
| `DEFINITION_OF_DONE.md` | the scorecard before "done" | 2 ✅ |
| `DOMAIN.md` | platform concepts → owning code; core flows | 2 ✅ |
| `ARCHITECTURE.md` | hub: diagram, layers, "add a new X" recipes (detail: `core/ARCHITECTURE.md`) | 2 ✅ |
| `CODE_STANDARDS.md` | hub over `DJANGO_STANDARDS` / `NEXTJS_STANDARDS`; gold-standard files | 2 ✅ |
| `UI_STANDARDS.md` | tokens, component kit, every page state, a11y, i18n | 2 ✅ |
| `TESTING.md` | the gate, what each change must test, architecture tests | 2 ✅ |
| `SECURITY.md` | hub over the security and auth specs | 2 ✅ |
| `PRODUCTION.md` | diagnosing a running instance | 2 ✅ |
| `RELEASE.md` | releasing the core (SemVer, manifest, core-guard) | 2 ✅ |
| `system-design/TRAPS.md` | trap · symptom · fix · source, by cost | 2 ✅ |

## Phases

| Phase | Work | State |
|---|---|---|
| 0 | Branch/worktree; truth audit of the existing docs against the code | ✅ |
| 1 | `PURPOSE.md`, `INVARIANTS.md` | ✅ |
| 2 | The standards set (parallel workers, disjoint files; every file reviewed) | ✅ |
| 3 | `AGENTS.md` § 0 "Follow the protocol" + need → read table + traps pointer (≤ 200 lines); `CLAUDE.md`/`GEMINI.md` stay imports; `.claude/rules`, `verify` skill and session hook point at the new docs | ✅ |
| 4 | `INDEX.md` rewritten around the set; stale claims from the audit fixed; one `TECH_DEBT.md` row for the over-long specs | ✅ |
| 5 | Link check, § 2 gate, fact check of every name/count/path, the fresh-agent test; `DAILY_CHANGES.md` entry; ask before commit | ✅ |

## Rules for this work
- Never name another codebase, company or client (AGENTS rule 5a). Final check: a case-insensitive `rg` for
  every such name known to the owner → zero hits.
- Never invent: every path, command, count and behaviour is read from the repo.
- Hubs stay short and link the deep `system-design/` specs by section; nothing is copied twice.
