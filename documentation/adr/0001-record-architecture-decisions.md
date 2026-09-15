# ADR-0001: Record architecture decisions

**Status:** Accepted
**Date:** 2026-09-15

## Context

DjangoBaseX is a boilerplate: every product copied from it inherits its shape. Choices made here —
which auth scheme, how permissions are modelled, how the frontend talks to the API — are expensive
to reverse once several products depend on them.

Undocumented decisions get re-litigated. Someone sees a pattern, assumes it was an accident, "fixes"
it, and the reasoning is gone. That is a recurring cost, and it grows with each copy of this repo,
because the person questioning the decision is increasingly unlikely to be the person who made it.

## Decision

We record architecture decisions as ADRs in `documentation/adr/`, numbered and immutable once
Accepted, registered in `documentation/ADR.md`.

An ADR is warranted when a choice constrains future work, is expensive to reverse, or will otherwise
be questioned repeatedly. Not every choice needs one.

An Accepted ADR is never edited to change its decision. A decision that turns out wrong gets a
**new** ADR that supersedes it, so the original reasoning — including why it was wrong — survives.

## Consequences

- A "why is it like this?" question has one place to look, and `AGENTS.md` § 4 sends agents there
  before any change to the shape of something.
- Writing one costs ten minutes and forces the alternatives to be named, which sometimes changes the
  decision.
- The register goes stale if rows aren't added. `AGENTS.md` § 4 makes adding the row part of the same
  change as the decision — the only arrangement that survives.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Comments in code | Invisible until you're already in the file, and lost on refactor |
| One big DECISIONS.md | Becomes append-only sludge; no status, no supersession |
| Nothing | The current cost, just paid later and repeatedly |
