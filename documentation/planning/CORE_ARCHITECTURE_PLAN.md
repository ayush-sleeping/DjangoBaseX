# Core Architecture Plan

**Goal:** make DjangoBaseX a core you copy into a new project and build on immediately, with
independent teams working in their own repos without touching the core.

**Status:** plan. Phase 0 is being built now; everything below Phase 2 is intent.
**Decided:** 2026-09-15 — seams first, plugins hold both halves, plugins ship as git submodules.

---

## 0. Where this comes from

This design combines two problems that are usually solved separately, because a core that is copied
into products has to solve both at once.

| Problem | What it demands | Mechanisms adopted |
|---------|-----------------|--------------------|
| **Reusability** — copy it, rename it, keep taking updates | The product's code must be separable from the platform's, and drift must be visible | `core/` vs `project/` split enforced by tests · a registry seam · a SHA manifest + drift doctor · clone-and-re-origin so `git merge core/main` works · a setup script that renames and re-secrets |
| **Parallel teams** — many modules, many repos, outside contributors | A team must be able to ship a module without touching, or being able to break, the core | One repo per plugin as a git submodule · auto-discovery through the framework's own app mechanism · plugin-prefixed permissions/tables/routes · **no cross-plugin imports** · a sandbox branch per external developer |

**What Django gives us for free.** Equivalent module systems in other frameworks need an extra
package and dependency-manager plumbing to get a service-provider per module. Django already has
this: `INSTALLED_APPS` is the plugin list and `AppConfig.ready()` is the service provider. The
backend plugin layer is genuinely less machinery here.

**One thing deliberately done differently.** The usual arrangement keeps all documentation in the
core repo, with plugins carrying no markdown. That suits a monorepo with one maintainer.
DjangoBaseX plugins are owned by separate teams, so **a plugin documents itself in its own repo**
and the core links to it. Centralising the docs would put every plugin's doc change through the
core's review queue, which is the bottleneck this whole design exists to remove.

---

## 1. The three layers

```
backend/
├── config/          composition root — settings, urls. Knows all three layers
├── core/            THE PLATFORM. Reusable. Imports NOTHING below it
├── project/         THIS product. One per copy of the boilerplate
└── plugins/         git submodules, one GitHub repo each
    └── <name>/
        ├── plugin.toml       metadata + declared prefixes
        ├── djx_<name>/       the Django app package
        └── frontend/         symlinked into frontend/src/plugins/<name>
```

| Layer | Owned by | Lives where | May import |
|-------|----------|-------------|-----------|
| **core** | the boilerplate maintainer | this repo | Django, third-party, `core.*` |
| **project** | the team that copied it | this repo | everything, including `core.*` |
| **plugin** | one team, one repo | its own repo | Django, third-party, `core.*` — **never another plugin, never `project`** |

### The one rule that makes it work

> **Dependencies point inward, and registration points outward.**
>
> `core` never imports `project` or any plugin. Instead `core` exposes registries, and `project` and
> plugins **register into them** at boot. Core ends up knowing *that* a nav section exists without
> ever knowing the word `billing`.

This is a well-proven shape. The measurement that motivates it is always the same: count the places
where the product reaches into the platform, and you find a handful of files, several of them one
big literal listing every module by name. The registry replaces each of those literals with a
registration call. **Nothing in core learns the word `billing` — the registry only ever holds a key,
a label and a way to ask.**

**Deleting `project/` and `plugins/*` from a fresh copy must leave a working platform.** That is the
property, and a test asserts it rather than a convention hoping for it.

---

## 2. The seam — `core/registry.py`

One module, no imports from `core.*` above it, holding the catalogs a plugin contributes to:

| Registry | A plugin registers | Core uses it for |
|----------|--------------------|------------------|
| `permissions` | a permission group + its permissions | the RBAC catalog, the roles screen |
| `navigation` | a sidebar section + items, each gated by a permission | the dashboard nav |
| `api_routes` | a URLconf module + prefix | `config/urls.py` includes it |
| `events` | event names it emits | the webhook subscription UI |
| `jobs` | periodic background jobs | the worker |
| `search` | a searchable entity + a query function | global search |
| `settings` | a settings schema | the configuration screen |
| `health` | a readiness check | `/api/health/ready` |

### Registration rules

1. **Boot-time and one-way.** Registration happens in `AppConfig.ready()`. There is no `unregister`
   — a registry that changes under a running app means the permission list depends on when you ask.
2. **Read-only after boot.** Catalogs are materialised once and frozen.
3. **`core/registry.py` imports nothing from `core`.** Anything a plugin imports to register must sit
   below it in the import graph, or the cycle comes back.
4. **A registry holds a key, a label, and a callable** — never a plugin's model, schema or vocabulary.

```python
# djx_billing/apps.py — the whole integration surface of a plugin
from django.apps import AppConfig
from core import registry

class BillingConfig(AppConfig):
    name = "djx_billing"
    label = "billing"                    # REQUIRED and explicit — see § 3

    def ready(self):
        from . import permissions, nav
        registry.permissions.register(permissions.GROUP)
        registry.navigation.register(nav.SECTION)
        registry.api_routes.register(prefix="billing", urlconf="djx_billing.urls")
```

---

## 3. Collision avoidance — four prefixes, all enforced

A plugin owns a namespace. Every one of these is checked by a test, because a convention that is only
written down is a convention that is already half-broken.

| Thing | Rule | Example |
|-------|------|---------|
| Django app label | `label = "<name>"`, set **explicitly** | `label = "billing"` |
| Database tables | `Meta.db_table` starts `<name>_` | `billing_invoices` |
| Permissions | `<name>.<feature>.<action>` | `billing.invoices.create` |
| API routes | mounted under `/api/<name>/`, url names `<name>:` | `/api/billing/invoices/` |
| Frontend routes | under `/(plugins)/<name>/` | `/billing/invoices` |

> ⚠️ **The app-label trap.** Django derives `app_label` from the last component of the package path.
> Every plugin package is `djx_<name>`, so labels would be unique — but a plugin that renames its
> package silently changes its label, and `app_label` is written into every migration. **Setting it
> explicitly is required**, and the conventions test fails a plugin that omits it.

---

## 4. Inter-plugin boundaries

**A plugin may not import another plugin.** Verified by an AST scan in the boundary test — not by
review, and not by a grep someone remembers to run.

When plugin A genuinely needs something from plugin B, in order of preference:

1. **A Django signal** B emits and A receives. Both stay decoupled.
2. **A contract in `core/contracts/`** that B implements and A resolves through the registry. Core
   defines the interface and knows neither party's vocabulary.
3. **A thin authenticated HTTP endpoint** A calls. Slowest, but a real boundary.

If you are about to write `from djx_other import ...`, stop and propose one of these.

---

## 5. Frontend

Next.js has no plugin system, so we build the smallest one that works.

```
frontend/src/
├── core/                    platform UI — never imports project/ or plugins/
├── project/                 this product's UI
├── plugins/<name>           symlink → ../../../backend/plugins/<name>/frontend
└── app/
    ├── (core)/              platform routes
    ├── (project)/           product routes
    └── (plugins)/[plugin]/[[...slug]]/page.tsx    one catch-all, resolved by registry
```

A plugin's frontend half ships **in the same repo as its backend half**, so one team makes one PR in
one repo for a whole feature. The symlink is created by `scripts/plugins.py link`.

**Route mounting** is a generated registry (`src/plugins/registry.generated.ts`) plus one catch-all
segment — the standard shape for mounting modules a build cannot know about ahead of time.

> **The honest cost:** a catch-all route gives up per-route static analysis, and every plugin page is
> resolved at runtime. The alternative — codegen writing a real route file per plugin page — keeps
> static routing but adds a build step that must run before `next dev` and goes stale silently.
> **Decision: start with the catch-all.** Revisit if per-route caching or metadata becomes a real
> requirement, and record it as an ADR then.

---

## 6. What enforces all of this

Convention is not enforcement. Every rule above has something that fails when it is broken.

| Check | Fails when |
|-------|-----------|
| `tests/architecture/test_core_boundary.py` | `core/` imports `project` or any plugin |
| `tests/architecture/test_plugin_boundary.py` | a plugin imports another plugin, or `project` |
| `tests/architecture/test_plugin_conventions.py` | a plugin is missing `plugin.toml`, an explicit label, or a required prefix |
| `frontend/tests/boundaries.test.ts` | `src/core/` imports `src/project/` or `src/plugins/` |
| `scripts/core_doctor.py` + `core.manifest.json` | a product copy has edited core — a SHA per core file |
| `.github/workflows/core-guard.yml` | a PR edits `core/` without the `core-change` label |
| `.github/workflows/ci.yml` | lint, format, Django checks, migrations, tests, typecheck, build |

The manifest is regenerated **only in this repo**. Regenerating it in a product copy records that
copy's drift as correct, which is worse than not having it.

---

## 7. Starting a product from this

Clone and re-origin. **Never "Use this template"** — a template repo shares no git history, so
`git merge core/main` has no common ancestor and the copy can never take a core update.

```bash
git clone https://github.com/ayush-sleeping/DjangoBaseX.git my-product
cd my-product
git remote rename origin core          # upstream — this is how updates arrive
git remote add origin <your repo>
./scripts/setup.sh                     # rename, fresh SECRET_KEY, migrate, seed
```

`setup.sh` does what the source project's does: takes the name from the directory, generates a
**fresh `SECRET_KEY`** — two products sharing a signing key is a cross-product session-forgery bug,
not an untidiness — writes the env files, migrates and seeds.

Taking a core update later: `git fetch core && git merge core/main`. Conflicts appear only in files
the product edited, which is why the core/project split earns its keep.

---

## 8. Phases

Ordered by dependency. Each phase leaves the repo working.

### Phase 0 — the seams (now)
- [ ] `core/` · `project/` · `plugins/` layout, `config/` as composition root
- [ ] `core/registry.py` — permissions, navigation, api_routes, events, jobs, search, settings, health
- [ ] `core/plugins.py` — discovery from `plugins/*/plugin.toml`, `sys.path`, `INSTALLED_APPS`
- [ ] `project/` skeleton with `wiring.py`
- [ ] The four architecture tests + pytest/pytest-django
- [ ] `scripts/plugins.py` — `new`, `link`, `list`
- [ ] A plugin template, and an `example` plugin proving the whole path end to end
- [ ] `frontend/src/{core,project,plugins}` + the catch-all + boundary test
- [ ] CI + core-guard workflows, `core_doctor.py`, `core.manifest.json`
- [ ] `setup.sh`

### Phase 1 — the platform worth reusing
Auth (resolve `TECH_DEBT` DB-1 first), RBAC through the permission registry, users CRUD as the
reference module, activity log, settings, the dashboard shell and nav.

### Phase 2 — making it pleasant
Docker Compose with Postgres + Redis, Celery, type generation from `/api/schema/`, seeders.

### Phase 3 — the second product
**The real test.** Nothing proves a core is reusable until something else is built on it. Whatever
hurts the second time is the design flaw, and it is cheaper to find at product two than at product
five.

---

## 9. Team workflow

A sandbox-branch pattern, which is what lets an outside contributor work on a plugin without being
able to break it.

| Who | Works where | Merges to `main` |
|-----|-------------|------------------|
| Core maintainer | this repo | yes |
| Product team | their copy's `project/` | in their own repo |
| Plugin team | their plugin repo, own branch | after review by the plugin owner |
| Outside contributor | a **sandbox branch** in the plugin repo | never — the owner cherry-picks |

**A core change needs a reason that applies to more than one product.** If it only serves yours, it
belongs in `project/`. If core genuinely cannot express something, that is a request for a **seam** —
and everyone gets it, not just you. Adding a seam is almost always better than adding a special case.
