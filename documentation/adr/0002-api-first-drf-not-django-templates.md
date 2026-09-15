# ADR-0002: The backend is an API only — DRF, no Django templates

**Status:** Accepted
**Date:** 2026-09-15

## Context

Django can serve HTML directly, and doing so is less machinery than running two processes. The
alternative is a JSON API consumed by a separate Next.js frontend.

Django's template layer is genuinely good, and choosing against it is a real trade. But this
boilerplate exists to produce products with a TypeScript frontend — the whole reason it is the
sibling of LaraBaseX rather than a copy of it. Mixing the two means every feature has to decide which
half it lives in, and that decision gets made inconsistently.

## Decision

The Django side is a **REST API only**, built with Django REST Framework. The only server-rendered
HTML is Django's own admin at `/admin/` and the drf-spectacular Swagger UI at `/api/docs/`.

All user-facing UI is Next.js. No Django template is added for a product feature.

## Consequences

- The API contract is explicit and documented — drf-spectacular generates OpenAPI at `/api/schema/`,
  which is a machine-readable artifact a hand-rendered template never produces.
- The frontend can be typed against that schema. 🔜 Generating TypeScript types from it is planned
  (`TECH_DEBT` DB-4) and is the payoff that makes this choice worth its cost.
- Two processes to run, two toolchains to install, CORS and CSRF to configure — all of which are
  already handled in `backend/config/settings.py` via `django-cors-headers` and env-driven
  `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS`.
- **Server-rendered SEO needs deliberate work on the Next side.** Django would have given it free.
- Django's admin stays. It is not a product surface — it is a staff tool, and rebuilding it in Next
  would be weeks of work for something that already exists and already respects the model layer.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Django templates + HTMX | Good stack, wrong one for this boilerplate's purpose |
| Django templates for public pages, Next for the app | Two frontends, two auth integrations, and a permanent question about where each new page goes |
| Inertia.js (as LaraBaseX uses) | Couples the two halves; loses the typed, independently-deployable API this exists to provide |
