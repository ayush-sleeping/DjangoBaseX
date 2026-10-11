# Architecture Decision Records

A settled decision lives in `adr/` as one numbered, immutable file. This page is the register.

**A decision listed as `Accepted` is settled.** Do not quietly change the code away from it — if the
decision was wrong or circumstances changed, write a **new** ADR that supersedes it and update the
row here. That way the reasoning survives, including the reasoning that turned out to be wrong,
which is the part people most need six months later.

**Write an ADR when** a choice constrains future work, is expensive to reverse, or will otherwise be
re-litigated every few months by someone who wasn't there. Not every choice needs one — a decision
nobody will question is just code.

Template: [`adr/0000-template.md`](adr/0000-template.md).

---

| # | Decision | Status | Date |
|---|----------|--------|------|
| [0001](adr/0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | 2026-09-15 |
| [0002](adr/0002-api-first-drf-not-django-templates.md) | The backend is an API only — DRF, no Django templates | Accepted | 2026-09-15 |
| [0003](adr/0003-uv-manages-the-backend-toolchain.md) | `uv` manages Python, the venv and dependencies | Accepted | 2026-09-15 |
| [0004](adr/0004-ruff-is-the-only-python-tool.md) | Ruff is the only Python lint/format tool | Accepted | 2026-09-15 |
| [0005](adr/0005-sqlite-for-dev-postgres-by-url.md) | SQLite for development, PostgreSQL via `DATABASE_URL` | Accepted | 2026-09-15 |
| [0006](adr/0006-one-agent-contract.md) | One agent contract, at the repository root | Accepted | 2026-09-15 |
| [0007](adr/0007-claude-code-harness.md) | `.claude/` enforces and points at the contract; it never holds rules | Accepted | 2026-10-07 |
| [0008](adr/0008-custom-user-model-email-identity.md) | A custom `users.User`, identified by email, with boolean states | Accepted | 2026-10-11 |
| [0009](adr/0009-jwt-in-httponly-cookies.md) | Browser auth is JWT in `httpOnly` cookies, backed by a database session row | Accepted | 2026-10-11 |
| [0010](adr/0010-platform-layer-is-logical.md) | The platform is a logical layer (`core`, `users`, `rbac`); product code lives in `project/` | Accepted | 2026-10-11 |
| [0011](adr/0011-no-organisation-in-core.md) | No organisation model in the core; scoping lives behind `visible_to()` | Accepted | 2026-10-11 |

---

## Status meanings

| Status | Means |
|--------|-------|
| **Proposed** | Written, not yet agreed. Do not build against it |
| **Accepted** | Settled. Build against it; changing it needs a superseding ADR |
| **Superseded** | Replaced. The row names the ADR that replaced it; the file stays for the reasoning |
| **Deprecated** | No longer applies, and nothing replaced it |
