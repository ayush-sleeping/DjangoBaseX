# ADR-0003: `uv` manages Python, the venv and dependencies

**Status:** Accepted
**Date:** 2026-09-15

## Context

A Python project needs a Python version, a virtualenv and a resolved dependency set. The
conventional stack is `pyenv` + `venv` + `pip` + a hand-maintained `requirements.txt`, which is three
tools, no lockfile, and a `requirements.txt` that records what someone installed rather than what
resolves.

"Works on my machine" in Python is almost always one of: a different interpreter minor version, an
unpinned transitive dependency, or a venv that was never recreated after a dependency changed.

## Decision

`uv` manages all three. `backend/pyproject.toml` declares dependencies, `backend/uv.lock` pins the
full resolved tree including transitives, and `uv sync` installs Python 3.12 if missing, creates
`.venv` and installs from the lock.

Every backend command runs through `uv run` — `uv run python manage.py ...`, `uv run ruff check .`.
There is no "activate the venv first" step, and `uv run` re-syncs if the lock moved.

`requires-python = ">=3.12"`, and `[tool.uv] package = false` because this is a Django project, not
an installable library.

## Consequences

- One tool to install (`brew install uv`), and a checkout is runnable in one command.
- `uv.lock` is committed, so two machines resolve identically. **It must be committed with any
  dependency change** — a `pyproject.toml` edit without the lock update is the failure this prevents.
- `uv` is young relative to pip. It is not what every Python developer has installed, and the README
  has to say so.
- CI, when it exists, installs `uv` rather than using `setup-python`'s pip cache.

## Alternatives considered

| Option | Why not |
|--------|---------|
| pip + requirements.txt | No lockfile; transitive versions drift silently |
| Poetry | Does the job; slower, and `uv` also manages the interpreter, which Poetry does not |
| pipenv | Effectively unmaintained relative to the alternatives |
| pip-tools | Solves locking only — still needs pyenv and venv alongside it |
