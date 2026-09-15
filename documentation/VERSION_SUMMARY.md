# Version Summary

**Shippable features, by version.** Coarser than [`DAILY_CHANGES.md`](DAILY_CHANGES.md): a reader
here wants to know *what this version can do*, not what was touched.

A refactor, a doc change or a fix nobody noticed does not get an entry. A capability that did not
exist before does.

---

## Unreleased

_Nothing shippable yet. The scaffold runs — Django serves `/api/health/` and Swagger UI, Next.js
renders a home page showing live backend health — but there is no authentication, no CRUD and no
deployable topology. See [`planning/ROADMAP.md`](planning/ROADMAP.md)._

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
