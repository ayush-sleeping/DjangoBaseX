---
paths:
  - "frontend/src/**"
  - "frontend/*.config.*"
---

# Working in `frontend/` — read before editing

This file holds no rules (ADR-0006, ADR-0007). It tells you where they are.

- `documentation/system-design/NEXTJS_STANDARDS.md`: read § 0 before writing any Next.js code. § 2 covers the API
  boundary (`src/lib/api.ts`), § 3 server vs client components, § 7 before you say it's done.
- `frontend/node_modules/next/dist/docs/`: the installed Next.js version's own guides. Trust them over memory.
- `AGENTS.md` § 1: why `frontend/AGENTS.md` is generated and never hand-edited. § 3: the frontend rows of the
  layer table.
- Finish with the `/verify` skill (the `AGENTS.md` § 2 gate).
