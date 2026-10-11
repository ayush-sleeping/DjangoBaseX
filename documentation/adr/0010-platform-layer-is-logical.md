# ADR-0010: The platform is a logical layer — `core`, `users`, `rbac` — and product code lives in `project/`

**Status:** Accepted
**Date:** 2026-10-11

## Context

`BUILD_ORDER` 1.6 asks for the backend to be split into `core/` (the platform) and `project/` (the
product), with `config/` as the composition root and the frontend mirrored, so that a product copied
from this repository can take core updates and **deleting `project/` leaves a working platform**.
`CORE_ARCHITECTURE_PLAN.md` § 1 draws `backend/core/` as "the platform".

By the time 1.6 arrived, the platform was already three Django apps side by side: `core` (registry,
gate, checks), `users` (identity) and `rbac` (authorization). `AUTH_BLUEPRINT.md` Ch. 2 split them
on purpose, because identity and authorization change for different reasons. Nesting `users` and
`rbac` physically under `backend/core/` would change every import path, and would need their app
labels pinned so the existing migrations and table names survive. That is a large rename that
changes nothing about the dependency rule itself.

## Decision

The **platform layer is logical**: the apps `core`, `users` and `rbac` *are* the platform, and stay
where they are. **Product code lives in `backend/project/`**, a Django app loaded only when the
directory exists, which mounts its API through `registry.api_routes` and registers into the
registries from `wiring.py`. `config/` remains the composition root and is the only place that
names both layers.

On the frontend, platform code lives in `src/core/` (`src/core/lib/…`) and platform routes in the
`src/app/(core)/` route group (URLs unchanged). Product code goes in `src/project/` and
`src/app/(project)/`.

**The rule:** the platform never imports `project` (or a plugin). It is enforced by
`tests/architecture/test_core_boundary.py` (backend, AST), an ESLint `no-restricted-imports` rule
(frontend), and `tests/architecture/test_platform_without_project.py`. That last test copies the
backend without `project/` and proves it still boots and routes.

## Consequences

- No migration, table or import path changed for the platform apps; the split cost one new app
  and the frontend move.
- "Is this file core?" is answered by a list (`PLATFORM_APPS` in the boundary test), not by a
  directory. **The list must grow when a platform app is added**, which is a convention the test
  can only partly enforce: it fails when a listed app imports `project`, but cannot know an
  unlisted new app is meant to be platform.
- The core manifest and drift doctor (`BUILD_ORDER` 4.2) must hash the platform apps by that same
  list, not by a `core/` prefix.
- A product's own apps beside `project/` (for example `backend/billing/`) are product code by
  default, and the boundary test treats every non-platform first-party package as importable only
  from outside the platform.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Physical nesting (`backend/core/users`, `backend/core/rbac`) | Matches the plan's drawing literally, but rewrites every import and needs pinned app labels to keep migrations valid. The dependency rule is the same either way |
| No `project/` at all; products edit the platform apps | The exact drift 1.6 exists to prevent: core updates stop merging cleanly |
| One `core` app holding identity and authorization too | Reverses `AUTH_BLUEPRINT.md` Ch. 2's deliberate split |
