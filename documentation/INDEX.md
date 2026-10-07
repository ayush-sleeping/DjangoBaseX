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
| **Understand what auth/RBAC designs get wrong** | [`system-design/AUTH_FAILURE_MODES.md`](system-design/AUTH_FAILURE_MODES.md) — the failure catalogue + design checklist |
| **Set up tests and CI** | [`planning/TESTING_STRATEGY.md`](planning/TESTING_STRATEGY.md) |
| **Understand what this is FOR — read this first** | [`VISION.md`](VISION.md) |
| **See every capability a strong base must have — the master map** | [`planning/PLATFORM_BLUEPRINT.md`](planning/PLATFORM_BLUEPRINT.md) |
| **Make something configurable / avoid hard-coding a value** | [`system-design/CONFIGURATION.md`](system-design/CONFIGURATION.md) |
| **Add a registry, a plugin seam, or a plugin contribution** | [`system-design/EXTENSIBILITY.md`](system-design/EXTENSIBILITY.md) |
| **Build list endpoints, errors, rate limits, tokens, uploads** | [`system-design/API_PLATFORM.md`](system-design/API_PLATFORM.md) |
| **Add a background job, webhook, integration or secret** | [`system-design/JOBS_AND_INTEGRATIONS.md`](system-design/JOBS_AND_INTEGRATIONS.md) |
| **Send a notification or an ops alert** | [`system-design/NOTIFICATIONS_AND_ALERTING.md`](system-design/NOTIFICATIONS_AND_ALERTING.md) |
| **Add logging, health checks, metrics or error tracking** | [`system-design/OBSERVABILITY.md`](system-design/OBSERVABILITY.md) |
| **Release, deploy, back up or restore** | [`system-design/OPERATIONS.md`](system-design/OPERATIONS.md) — with [`system-design/DEPLOYMENT.md`](system-design/DEPLOYMENT.md) |
| **Build frontend platform pieces (data layer, tables, nav, theming)** | [`system-design/FRONTEND_PLATFORM.md`](system-design/FRONTEND_PLATFORM.md) |
| **Audit, retention, soft delete, provenance, scoping** | [`system-design/DATA_LIFECYCLE.md`](system-design/DATA_LIFECYCLE.md) |
| **Money, numbering, state machines, bulk, import/export** | [`system-design/DOMAIN_PRIMITIVES.md`](system-design/DOMAIN_PRIMITIVES.md) |
| **Build an optional module (billing, approvals, help centre…)** | [`system-design/REUSABLE_MODULES.md`](system-design/REUSABLE_MODULES.md) |
| **Review a change for the bugs that keep recurring** | [`system-design/BUG_CLASSES.md`](system-design/BUG_CLASSES.md) |
| **Write tests that can fail, gates that run, docs that stay true** | [`system-design/ENGINEERING_PRACTICES.md`](system-design/ENGINEERING_PRACTICES.md) |
| **Learn from mistakes other codebases already made** | [`system-design/LESSONS_LEARNED.md`](system-design/LESSONS_LEARNED.md) |
| **Understand the repo end to end, day one** | [`ONBOARDING.md`](ONBOARDING.md) |
| **Know what actually exists vs what's planned** | [`planning/ROADMAP.md`](planning/ROADMAP.md) |
| **Know what to build next, concretely** | [`planning/BUILD_ORDER.md`](planning/BUILD_ORDER.md) — the executable backlog |
| **Know how the two halves fit together** | [`core/ARCHITECTURE.md`](core/ARCHITECTURE.md) |
| **Write backend code** | [`system-design/DJANGO_STANDARDS.md`](system-design/DJANGO_STANDARDS.md) |
| **Write frontend code** | [`system-design/NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md) |
| **Design or change a model** | [`system-design/DATA_MODEL.md`](system-design/DATA_MODEL.md) — ⚠️ 5 decisions before the first migration |
| **Add an endpoint** | [`system-design/API_DESIGN.md`](system-design/API_DESIGN.md) |
| **Work on permissions or roles** | [`system-design/RBAC_DESIGN.md`](system-design/RBAC_DESIGN.md) |
| **Build auth / authz / RBAC — the full spec** | [`system-design/AUTH_BLUEPRINT.md`](system-design/AUTH_BLUEPRINT.md) — tables, files, flows, fail-closed machinery |
| **Anything security-sensitive** | [`system-design/SECURITY.md`](system-design/SECURITY.md) |
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
├── VISION.md             what this is for, and the priority order when designs conflict
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
