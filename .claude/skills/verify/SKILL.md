---
name: verify
description: Run the AGENTS.md § 2 verification gate on what changed, and report the real output. Use before saying any task is done, before asking to commit, and after a subagent hands work back.
allowed-tools: Bash(git status *) Bash(git diff *) Bash(uv run ruff check *) Bash(uv run ruff format --check *) Bash(uv run python manage.py check) Bash(uv run python manage.py makemigrations --check --dry-run) Bash(npm run lint) Bash(npx tsc --noEmit) Bash(python3 .claude/hooks/test_agent_guard.py)
---

# Verify

The gate commands are defined in `AGENTS.md` § 2. This skill is the procedure for running them. If the two
ever disagree, `AGENTS.md` wins. Fix this file.

## What changed

!`git status --porcelain`

## Procedure

1. **Pick the halves from the paths above.** Run every check for each half that changed.
   - Anything under `backend/`: `ruff check .`, `ruff format --check .` and `manage.py check`, each run from
     `backend/` with `uv run`.
   - Also any `models.py` or `migrations/` path: `makemigrations --check --dry-run`. This one is never optional.
   - Anything under `frontend/`: `npm run lint` and `npx tsc --noEmit`, from `frontend/`.
   - Anything under `.claude/hooks/`: `python3 .claude/hooks/test_agent_guard.py`.
   - Documentation only: no code gate. Check that every link you added resolves and every path you cite exists.
2. **Run each command separately** so that one failure doesn't hide the next.
3. **Do not fix and re-run silently.** If a check fails, show the failing output, fix it, re-run, and report
   both runs.
4. **Do not run `npm run build`** unless the user asked for it and the dev server is stopped (`AGENTS.md` § 2).

## Report

Give one line per check: the command, then ✅ or ❌. Quote the output of any failure verbatim. List every
check you skipped and why. A green summary over a red run is the one unrecoverable mistake (`AGENTS.md` § 1
rule 9).
