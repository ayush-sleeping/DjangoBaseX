# Version Summary

**Shippable features, by version.** Coarser than [`DAILY_CHANGES.md`](DAILY_CHANGES.md): a reader
here wants to know *what this version can do*, not what was touched.

A refactor, a doc change or a fix nobody noticed does not get an entry. A capability that did not
exist before does.

---

## Unreleased

- **Sign in** (2026-10-11): email + password login into `httpOnly` cookie JWTs, rotating refresh
  tokens with reuse detection and a two-tab grace window, logout, sign-out-everywhere-else and
  `/api/auth/me/`, with a minimal `/login` page ([ADR-0009](adr/0009-jwt-in-httponly-cookies.md)).
  Not deployable yet: no throttling, lockout, password reset or RBAC. See
  [`planning/ROADMAP.md`](planning/ROADMAP.md).

---

### Format

```markdown
## v0.2.0 — YYYY-MM-DD

**Added**
- Feature, described by what a user can now do.

**Changed**
- Behaviour that differs from the previous version.

**Fixed**
- A bug that was affecting people, and how it showed up.

**Breaking**
- What a product copied from an earlier version must change. Be specific; this is the section
  people read.
```
