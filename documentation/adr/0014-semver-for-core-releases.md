# ADR-0014: Core releases are versioned with SemVer

**Status:** Accepted
**Date:** 2026-11-06

## Context

Products are copied from this repository and later take core updates (`UPGRADING.md`, `core.manifest.json`,
`core_doctor`). Each product needs to know, before it upgrades, whether an update will cost it work.
`PLATFORM_BLUEPRINT.md` § 6 left pending decision #5 open: *SemVer or CalVer*. `OPERATIONS.md` already
proposed SemVer for the core and CalVer for a product's own deploy tags.

## Decision

Core releases are tagged `vMAJOR.MINOR.PATCH`. **MAJOR** means taking the update needs work in a product: a
seam, registry contribution shape, setting or contract changed. **MINOR** means new capability that a
product can take without changes. **PATCH** means fixes only. The version lives in `VERSION` and
`core.manifest.json`, and each release has upgrade notes. Products keep their own deploy tagging, which
`OPERATIONS.md` describes as CalVer. This record doesn't change that.

## Consequences

- **Easier:** a product can read the cost of an upgrade from the version number alone.
- **Harder:** every change to core has to be classified honestly. A breaking change shipped as a MINOR
  breaks the promise, so "what counts as breaking" needs to be written down (BUILD_ORDER 9.6, upgrade notes).

## Alternatives considered

| Option | Why not |
|--------|---------|
| CalVer (`vYYYY.MM.N`) for core | Says when, not what it costs. Products would have to read every changelog to find breaking changes |
