# ADR-0004: Ruff is the only Python lint/format tool

**Status:** Accepted
**Date:** 2026-09-15

## Context

The usual Python quality stack is Black (format) + isort (imports) + Flake8 (lint) + its plugins —
four tools, four configs, and a standing risk that the formatter and the linter disagree and fight
each other on every save.

## Decision

Ruff does linting, import sorting and formatting. It is the only Python quality tool in
`backend/pyproject.toml`, configured there:

- `line-length = 100`, `target-version = "py312"`
- `select = ["E", "F", "I", "B", "UP", "DJ"]` — pycodestyle, pyflakes, isort, bugbear, pyupgrade,
  and **`DJ` (flake8-django)**, which catches Django-specific mistakes like a `ForeignKey` without
  an explicit `on_delete` or a model without `__str__`
- `exclude = ["migrations", ".venv"]` — generated migrations are not hand-written code and
  reformatting them produces noise in every diff
- `known-first-party = ["config", "core"]` — **add each new Django app here** when you create it, or
  its imports sort as third-party

Both `ruff check .` and `ruff format --check .` are in the verification gate (`AGENTS.md` § 2).

## Consequences

- One config, one tool, no formatter/linter conflict.
- Fast enough that running it on every change is not a decision.
- `known-first-party` is a manual step that is easy to forget. The symptom is subtle: a new app's
  imports land in the wrong block and `ruff check` starts failing on files nobody touched.
- 🔜 Ruff does not type-check. `mypy` is planned (`TECH_DEBT` DB-3) and is a separate decision.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Black + isort + Flake8 | Four tools, four configs, and the conflicts this avoids |
| Ruff lint + Black format | Two formatters' worth of config for one job |
| No formatter | Style becomes a code-review topic, which is the worst place for it |
