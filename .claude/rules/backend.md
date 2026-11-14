---
paths:
  - "backend/**/*.py"
---

# Working in `backend/` — read before editing

This file holds no rules (ADR-0006, ADR-0007). It tells you where they are.

- `AGENTS.md` § 3: the layer table. Views, services, serializers, models and querysets each have one job.
- `documentation/CODE_STANDARDS.md`: the gold-standard file to copy for each kind (model, service, view, test…)
  and every rule with its check. `documentation/ARCHITECTURE.md` § How to add: recipes for a new app,
  endpoint, permission, job, setting, flag. `documentation/INVARIANTS.md`: what no change may break.
- `documentation/system-design/TRAPS.md` § Backend: traps that already cost time — check before debugging.
- `documentation/system-design/DJANGO_STANDARDS.md`: § 1 running anything (`uv run`), § 2 creating an app,
  § 3 layers, § 5 queries, § 6 API conventions, § 9 before you say it's done.
- `documentation/system-design/API_DESIGN.md`: read it before adding or changing an endpoint.
- `documentation/system-design/SECURITY.md`: read it before touching auth, permissions or input handling.
- `documentation/planning/TECH_DEBT.md`: known defects. Check it before reporting one as new.
- Finish with the `/verify` skill (the `AGENTS.md` § 2 gate).
