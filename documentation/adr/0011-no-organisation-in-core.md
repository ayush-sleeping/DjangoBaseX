# ADR-0011: No organisation model in the core; scoping lives behind `visible_to()`

**Status:** Accepted
**Date:** 2026-10-11

## Context

`DATA_MODEL.md` D3 asks whether rows belong to an `Organisation` or only to a `User`. It is the most
structural of the five data-model decisions, because the answer reaches every table and every query
a product will ever write.

The two options are laid out in `REUSABLE_MODULES.md` § 10.1:

- **A, no tenant in core.** The core has users only. A product that needs tenancy adds it.
- **B, a core-owned organisation table.** Every product inherits `core_organisation` and a
  membership, and the auth path branches on organisation status.

The evidence against A is concrete. In one mature codebase, adding tenancy after the fact meant
**a sweep across roughly 258 function signatures**. Until the tenant table moved into the core, the
core schema could not even be created without a product table (`TECH_DEBT.md` DB-23 asked for that
number to be recorded whichever way D3 went). The evidence against B is that every single-tenant
product carries a table with one row, a membership check that always passes, and an auth branch
that is never taken.

The owner decided on 2026-10-11, choosing "No org in core". No planned product is known to need
tenancy, and the core is not to carry it speculatively.

## Decision

The core has **no organisation model**. Rows belong to users. **Every model a non-superuser can
list exposes `Model.objects.visible_to(user)`**, a queryset method that fails closed (an unknown
caller sees nothing), and views read through it, never through a bare `.filter()`
(`DATA_MODEL.md` § 5). That method exists **because of this decision**: it is where a product adds
tenancy, so the change is one method per model rather than every view. Removing it as a
"simplification" reopens this ADR.

## Consequences

- Single-tenant products, the expected case, carry nothing: no table, no membership, no auth branch.
- **The cost is deferred, not removed.** A product that later needs tenancy pays it. `visible_to()`
  keeps the read side to one method per model, but writes (`writable_by()` /
  `assert_writable()`, `REUSABLE_MODULES.md` § 10.2), unique constraints that must become
  per-tenant, background jobs, exports and caches all still need the tenant threaded through. The
  ~258-signature figure above is what that looks like when the seam was *not* there. With the seam
  it should be much smaller, but nobody has measured it.
- The rule only works if it is enforced. A view calling `.filter()` on a listable model instead of
  `.visible_to()` is a review blocker (`DATA_MODEL.md` § 5, `BUG_CLASSES.md`). An architecture test
  for it is worth adding once the first listable product model exists.
- If tenancy is needed, `REUSABLE_MODULES.md` § 10.2 still sets the rules: registered scopes, reads
  and writes scoped separately, and a tenant header that is display only, never authority. Those
  rules then live in the product or in a tenancy plugin, not in the core.
- A product that knows on day one that it is multi-tenant should add its organisation model before
  its first migration. That costs the least, and it is a product decision, not a core change.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **B: a core-owned `core_organisation` table and membership** | Every product pays for it, and the auth path gains a status branch most products never take. It is the right choice for a base that mostly serves B2B SaaS or reseller products. Nothing planned says this one does |
| **A without a mandatory `visible_to()`** | The cheapest now, and the 258-signature retrofit later. The seam costs one method per model, so it is not worth saving |
| **Decide later** | D3 must be settled before the first product model's migration (`DATA_MODEL.md` § 6), and the core already has models (`users`, `rbac`). Deferring would mean deciding by accident |
