# `src/project/` — product code

This boilerplate's frontend has two layers (ADR-0010, a logical split):

| Layer | Where | What |
|-------|-------|------|
| **Core** | `src/core/**`, routes in `src/app/(core)/**` | The platform: the API client, auth, permissions, users, roles. Shared by every product copied from this repository |
| **Project** | `src/project/**`, routes in `src/app/(project)/**` | One product's own screens and logic |

**The one rule: project may import core; core never imports project.** Project code imports
`@/core/...` freely. Nothing under `src/core/` or `src/app/(core)/` may import `@/project/...`,
`@/app/(project)/...`, or reach `src/project/` by a relative path. ESLint enforces it
(`frontend/eslint.config.mjs`), so `npm run lint` fails on the first such import.

Why: a product takes core updates by replacing core's files. That only works while core knows nothing
about any product.

- Product logic goes here, in `src/project/lib/`, with the same rules as core: data through
  `@/core/lib/api` (never `fetch()` inline), logic in a lib module, never in a page.
- Product routes go in `src/app/(project)/`. A route group adds nothing to the URL, so
  `src/app/(project)/billing/page.tsx` serves `/billing`. Two groups must not serve the same path.
- Gate product screens on the product's own permission codes with `can()` from
  `@/core/lib/permissions`, exactly as core's screens do.
