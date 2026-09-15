# ADR-0006: One agent contract, at the repository root

**Status:** Accepted
**Date:** 2026-09-15

## Context

AI agents work in this repository continuously, and they need to be told the rules. The rules can
live in one file or several — per-directory contracts are tempting, because backend rules and
frontend rules are genuinely different.

The upstream core this contract was adapted from (`Leapswitch-Networks/core-fastapi-nextjs`) tried
the split and retired it. Its ADR-0016 records what went wrong: the two files drifted on a security
claim, so one said a design was accepted debt while the other had struck it through as forbidden.
About fifteen rules were being maintained in both. And the second file was loaded anyway, so the
split saved nothing.

Two contracts do not fail by going slightly stale. They fail by giving opposite instructions with no
way to tell which is current.

## Decision

There is exactly **one** agent contract: `AGENTS.md` at the repository root. `CLAUDE.md` imports it
and contains no rules of its own. No second contract is added under `documentation/` or in an app
directory.

`frontend/AGENTS.md` is the one exception, and it is not ours: `next dev` generates and re-adds it
(`frontend/node_modules/next/dist/server/lib/generate-agent-files.js`). It is never hand-edited —
anything written there is lost on the next `next dev`. Frontend rules go in the root `AGENTS.md` or
in `documentation/system-design/NEXTJS_STANDARDS.md`.

`documentation/INDEX.md` is deliberately **not** imported. Imports load eagerly into every session,
and the doc map matters a few times per task rather than every turn.

## Consequences

- One file to update, and it is impossible for two rules to contradict each other.
- The root contract carries backend and frontend rules together and is longer than either would be
  alone. That is the accepted cost; it is still shorter than two files plus the reconciliation.
- Everything in `AGENTS.md` is in context on every turn, so it has to stay short enough to be worth
  that. Detail belongs in `documentation/`, reachable through § 6.

## Alternatives considered

| Option | Why not |
|--------|---------|
| `backend/AGENTS.md` + `frontend/AGENTS.md` | Subdirectory `AGENTS.md` files are never auto-discovered — only `CLAUDE.md` is. They would not load |
| Rules in `CLAUDE.md`, workflow in `AGENTS.md` | The exact split that produced the contradiction described above |
| Rules in `README.md` | The README is for humans getting started; mixing the two makes both worse |
