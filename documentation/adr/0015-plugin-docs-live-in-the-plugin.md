# ADR-0015: A plugin documents itself; core documents only the contract

**Status:** Accepted
**Date:** 2026-11-06

## Context

Plugins (Phase 3, `scripts/plugins.py`, `examples/plugins/notes`) are developed and versioned apart from the
core, often by separate teams. `PLATFORM_BLUEPRINT.md` § 6 left pending decision #4 open: *where plugin
documentation lives*. `ENGINEERING_PRACTICES.md` § 35 recommended keeping it in each plugin.

## Decision

Each plugin ships its own documentation in its own repository and versions it with its code: a `README.md`,
a `docs/` folder for anything longer, and `help/` for in-app help pages. Its `PluginMeta` declares
`docs_url`. Core documents only the plugin contract, the template (`scripts/plugin_template/`) and the
example, and never copies a plugin's docs.

## Consequences

- **Easier:** a plugin's docs change in the same commit as its code, reviewed by the people who own it.
- **Easier:** core's docs stay limited to code core owns, so they don't drift from code they don't control.
- **Harder:** there's no single place that lists every plugin's docs. Discovery depends on `docs_url` and
  on whatever index a product builds.
- **Harder:** the docs lint (BUILD_ORDER 9.6) has to run in each plugin's CI, not just core's.

## Alternatives considered

| Option | Why not |
|--------|---------|
| All plugin docs in core | Every plugin doc change would go through core's review, and core's docs would track code it doesn't own |
