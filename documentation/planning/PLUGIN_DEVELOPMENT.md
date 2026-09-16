# Creating a Plugin

**The guide for a developer who owns one plugin and should never need to touch the core.**

**Status:** 🔜 the mechanism is Phase 0 of
[`CORE_ARCHITECTURE_PLAN.md`](CORE_ARCHITECTURE_PLAN.md). This is the intended contract; the
checklist is written so it can be followed the day the seam lands.

Adapted from PriorCoreB's `PLUGIN_ARCHITECTURE.md`, which runs four plugins in four repos with outside
contributors — the arrangement this is copying.

---

## What a plugin is

**Its own GitHub repo**, mounted as a git submodule at `backend/plugins/<name>/`, holding **both
halves** of a feature:

```
plugins/billing/                  ← the submodule root = your repo root
├── plugin.toml                metadata + declared prefixes
├── README.md                  your plugin's docs live HERE, in your repo
├── djx_billing/                  the Django app package
│   ├── apps.py                registers into core — the entire integration surface
│   ├── models.py              db_table = "billing_*"
│   ├── urls.py · views.py · serializers.py · services.py
│   ├── permissions.py         the permission catalog
│   ├── migrations/
│   └── tests/
└── frontend/                  symlinked into frontend/src/plugins/billing
    ├── pages/
    └── components/
```

One repo, one team, one PR per feature. You never open a PR against the core to ship a feature.

---

## The five hard rules

Each one is enforced by a test, not by review. They exist because without them two plugins silently
collide and the failure surfaces in production.

| # | Rule | Example |
|---|------|---------|
| 1 | **Explicit app label** — `label = "billing"` in `AppConfig` | Django derives it from the package path otherwise, and it is baked into every migration |
| 2 | **Table prefix** — every `Meta.db_table` starts `<name>_` | `billing_quotes` |
| 3 | **Permission prefix** — `<name>.<feature>.<action>` | `billing.quotes.create` — never a bare `view` or `create` |
| 4 | **Route prefix** — `/api/<name>/`, url names `<name>:` | `/api/billing/quotes/` |
| 5 | **No cross-plugin imports** — `from djx_other import …` is forbidden | see below |

### Rule 5 in practice

PriorCoreB has held this to **zero violations across four plugins**. When plugin A genuinely needs
something from plugin B, in order of preference:

1. **A Django signal** B emits and A receives — both stay decoupled
2. **A contract in `core/contracts/`** that B implements and A resolves through the registry
3. **A thin authenticated HTTP endpoint** A calls — slowest, but a real boundary

If you are about to write `from djx_other import ...`, stop and propose one of these in the PR.

---

## Your entire integration surface

```python
# djx_billing/apps.py
from django.apps import AppConfig
from core import registry

class BillingConfig(AppConfig):
    name = "djx_billing"
    label = "billing"                       # REQUIRED — rule 1

    def ready(self):
        from . import permissions, nav
        registry.permissions.register(permissions.GROUP)
        registry.navigation.register(nav.SECTION)
        registry.api_routes.register(prefix="billing", urlconf="djx_billing.urls")
```

That is the whole contract. **Core never imports your plugin** — it exposes registries and you
register into them at boot. Core ends up knowing a nav section exists without ever knowing the word
`billing`.

Registration is **boot-time and one-way**: it happens in `ready()`, there is no `unregister`, and
the catalogs are read-only afterwards. A registry that could change under a running application
would mean the permission list depended on when you asked.

---

## Checklist for a new plugin

- [ ] Create the GitHub repo
- [ ] `git submodule add <url> backend/plugins/<name>`
- [ ] Write `plugin.toml` — name, label, version, minimum core version
- [ ] Create `djx_<name>/` with `apps.py` per the template above
- [ ] `permissions.py` — the permission group, every name prefixed (rule 3)
- [ ] `urls.py` — routes prefixed and named (rule 4)
- [ ] Models with `db_table` prefixed (rule 2), then `makemigrations <name>`
- [ ] `frontend/` half, and `scripts/plugins.py link` to symlink it
- [ ] At least one smoke test per half
- [ ] Run the full gate from `AGENTS.md` § 2, plus the architecture tests
- [ ] Document the plugin in **your repo's** `README.md`
- [ ] Bump the submodule pointer in the core repo **in the same PR** as any dependent core change

---

## Working with outside contributors

PriorCoreB's pattern, which is what lets an external admin work on a plugin without being able to
break production:

| Branch | Who | Rule |
|--------|-----|------|
| `main` | the plugin owner | production. **Only the owner merges** |
| `sandbox/<person>` | one outside contributor | they own it, push freely, never merge to `main` |

When the contributor says a change is ready, the owner **reviews the diff and cherry-picks or merges
the specific commits** into `main`, pushes, then bumps the submodule pointer in the core repo.

**Never auto-merge a sandbox branch.** The value is entirely in the review step; automating it
removes the only thing the arrangement is for.

---

## Everyday submodule commands

```bash
git clone --recurse-submodules <core repo>     # first time
git submodule update --init --recursive        # existing clone

cd backend/plugins/billing                        # work in your plugin
git checkout main && git pull
# ... edit, commit, push — this is YOUR repo ...

cd ../../..                                    # back in core
git add backend/plugins/billing
git commit -m "chore(plugins): bump billing to <short-sha>"
```

> ⚠️ **A submodule pointer bump is a real commit in the core repo.** Forgetting it means your work is
> pushed but the core still points at the old SHA, so nobody else — and no deploy — sees it. This is
> the most common submodule mistake and it looks exactly like "my change vanished".
