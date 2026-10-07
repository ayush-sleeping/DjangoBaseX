---
paths:
  - "backend/**/models.py"
  - "backend/**/models/**/*.py"
  - "backend/**/migrations/**"
---

# Changing a model or a migration — read before editing

This file holds no rules (ADR-0006, ADR-0007). It tells you where they are.

- `documentation/system-design/DATA_MODEL.md`: § 1 has the five decisions to make before the first migration.
  § 6 is the checklist.
- `documentation/system-design/DATABASE_MIGRATIONS.md`: the routine, non-nullable fields on populated tables,
  and merge conflicts.
- `AGENTS.md` § 2: the `makemigrations --check --dry-run` gate. § 5: migrations are never generated in parallel.
- `AGENTS.md` § 1 rule 4: ask before resetting migrations or dropping tables.
