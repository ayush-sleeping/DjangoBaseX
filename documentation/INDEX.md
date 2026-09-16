# Documentation Index

**This is the doc map.** It exists so you read the one file you need rather than all of them. Find
your task below, read the **Start Here** file, and stop.

> Every doc in this tree says what is **true today**. Where something is planned rather than built,
> it is marked 🔜 — and if you find a doc describing code that does not exist, that is a bug in the
> doc; fix it in the same change.

---

## I want to…

| Task | Start here |
|------|-----------|
| **Get the thing running on my machine** | [`../README.md`](../README.md) § Getting Started |
| **Start a NEW product from this boilerplate** | [`NEW_PROJECT.md`](NEW_PROJECT.md) |
| **Take a core update into my product** | [`UPGRADING.md`](UPGRADING.md) |
| **Build a plugin / work as a separate team** | [`planning/PLUGIN_DEVELOPMENT.md`](planning/PLUGIN_DEVELOPMENT.md) |
| **Understand the core + plugin architecture** | [`planning/CORE_ARCHITECTURE_PLAN.md`](planning/CORE_ARCHITECTURE_PLAN.md) |
| **Decide the auth model (blocking)** | [`planning/AUTH_RND.md`](planning/AUTH_RND.md) |
| **Set up tests and CI** | [`planning/TESTING_STRATEGY.md`](planning/TESTING_STRATEGY.md) |
| **Understand the repo end to end, day one** | [`ONBOARDING.md`](ONBOARDING.md) |
| **Know what actually exists vs what's planned** | [`planning/ROADMAP.md`](planning/ROADMAP.md) |
| **Know how the two halves fit together** | [`core/ARCHITECTURE.md`](core/ARCHITECTURE.md) |
| **Write backend code** | [`system-design/DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) |
| **Write frontend code** | [`system-design/NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md) |
| **Change the database schema** | [`system-design/DATABASE_MIGRATIONS.md`](system-design/DATABASE_MIGRATIONS.md) |
| **Deploy it** | [`system-design/DEPLOYMENT.md`](system-design/DEPLOYMENT.md) — ⚠️ read § 0 first |
| **Know why something is built this way** | [`ADR.md`](ADR.md) |
| **Find a known bug before re-reporting it** | [`planning/TECH_DEBT.md`](planning/TECH_DEBT.md) |
| **See what changed recently** | [`DAILY_CHANGES.md`](DAILY_CHANGES.md) |
| **See what shipped, by version** | [`VERSION_SUMMARY.md`](VERSION_SUMMARY.md) |
| **Know the rules I'm working under** | [`../AGENTS.md`](../AGENTS.md) — the operating contract |

---

## The tree

```
documentation/
├── INDEX.md              ← you are here
├── ONBOARDING.md         first day, end to end
├── NEW_PROJECT.md        starting a product from this boilerplate
├── UPGRADING.md          taking a core update into a product
├── ADR.md                the decision register — one row per ADR
├── DAILY_CHANGES.md      the running log; one entry per task
├── VERSION_SUMMARY.md    shippable features, by version
├── adr/                  the decision records themselves
├── core/                 how the built subsystems work
├── system-design/        conventions and standards you must follow
└── planning/             intent — roadmaps, plans, tech debt
```

### What belongs in which folder

| Folder | Holds | Does **not** hold |
|--------|-------|-------------------|
| `adr/` | One settled decision per file, immutable once Accepted. Superseded by a new ADR, never edited | Plans, conventions, tutorials |
| `core/` | How a **built** subsystem actually works — auth, RBAC, the API surface | Anything not yet built |
| `system-design/` | Conventions you must follow when writing code | Explanations of what exists |
| `planning/` | **Intent.** Roadmaps, multi-session plans, ranked defects | Anything presented as current state |

**The distinction that matters:** `core/` and `system-design/` describe reality; `planning/`
describes intent. Reading a planning doc as though it were current state is the single most common
way to waste an afternoon here. Check the code.

---

## Adding a doc

1. Put it in the right folder per the table above
2. **Add a row to this file** in the same change — a doc not listed here will not be found
3. If it records a decision, add a row to [`ADR.md`](ADR.md) too
