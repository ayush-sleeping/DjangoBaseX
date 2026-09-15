# ADR-0005: SQLite for development, PostgreSQL via `DATABASE_URL`

**Status:** Accepted
**Date:** 2026-09-15

## Context

A boilerplate's first-run experience decides whether anyone gets to the interesting part. Requiring
PostgreSQL before `runserver` works means installing a server, creating a role and a database, and
debugging `pg_hba.conf` — before seeing a single page.

But SQLite is not what a product runs in production, and the gaps are real: no `JSONField` operators
at parity, different constraint enforcement timing, no concurrent writers, and `ArrayField` and other
`django.contrib.postgres` fields simply absent.

## Decision

`backend/config/settings.py` defaults to SQLite (`db.sqlite3`). Setting `DATABASE_URL` in `.env`
switches to PostgreSQL — no code change, per `django-environ`'s URL parsing.

**SQLite is a development convenience, not a supported deployment target.** Any product copied from
this boilerplate sets `DATABASE_URL` before it ships.

## Consequences

- A fresh clone runs after `uv sync` + `migrate`, with nothing else installed. That is the point.
- `db.sqlite3` is gitignored — a committed one would ship someone's local rows to every copy.
- **Postgres-only features can be used and will pass locally.** A `JSONField` query or a
  `django.contrib.postgres` import works against Postgres and fails on SQLite, or vice versa, and
  nothing currently catches it — there is no test suite and no CI. Until there is, developing a
  feature that touches Postgres-specific behaviour means setting `DATABASE_URL` locally first.
- 🔜 When CI exists it should run against PostgreSQL 16, matching what products deploy. A suite that
  proves behaviour against a database nobody runs proves it in the wrong place.

## Alternatives considered

| Option | Why not |
|--------|---------|
| PostgreSQL required from the start | Kills the one-command first run, which is most of a boilerplate's value |
| Docker Compose Postgres by default | Better, and planned 🔜 — but Docker is a second prerequisite, and this decision can be revisited when the Compose setup lands |
| SQLite only | Not a production database for anything this boilerplate is for |
