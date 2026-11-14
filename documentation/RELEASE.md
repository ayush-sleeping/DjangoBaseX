# DjangoBaseX — releasing the core

> **Status:** Hub — checked 2026-11-14 · Core versioning, the manifest and its guard are built; `VERSION` is `0.1.0`, no git tag exists yet, and per-release upgrade notes (BUILD_ORDER 9.6) are done; the product deploy driver, backups and release images exist since 9.5 but have not been run against a real server. This doc releases **this boilerplate**; a product built on it deploys per `system-design/OPERATIONS.md`.

Context: [`PURPOSE.md`](PURPOSE.md), [`INVARIANTS.md`](INVARIANTS.md), [`TESTING.md`](TESTING.md).

## Versioning (ADR-0014)

Core releases are tagged `vMAJOR.MINOR.PATCH`. The version lives in the `VERSION` file and in `core.manifest.json` (`version` key). See [ADR-0014](adr/0014-semver-for-core-releases.md).

| Bump | Means | Test |
|---|---|---|
| **MAJOR** | Taking the update needs work in a product: a seam, registry contribution shape, setting or contract changed | Would a product's merge need an edit outside `core/`? |
| **MINOR** | New capability a product takes unchanged | |
| **PATCH** | Fixes only | |

Classify honestly: a breaking change shipped as MINOR breaks the promise. A removed env key or setting (e.g. `REAUTH_*` moved to runtime settings) is breaking and gets a **Breaking** bullet in `VERSION_SUMMARY.md`.

## Release steps

1. **Gate is green** — the `AGENTS.md` § 2 commands, with the owner present.
2. **Docs in the same change** (`AGENTS.md` § 1 rule 8):
   - [`DAILY_CHANGES.md`](DAILY_CHANGES.md): one entry per task (What / Why / Files / Verification), newest first.
   - [`VERSION_SUMMARY.md`](VERSION_SUMMARY.md): a capability that did not exist before goes under `## Unreleased`, then moves under the version heading at release. Refactors and unnoticed fixes get no entry.
   - [`CHANGELOG.md`](../CHANGELOG.md): one line under `## Unreleased` per shipped change, with its **Upgrade notes** (env keys added or removed, `set_setting`, migration order); `## Unreleased` becomes the version heading at release.
   - [`UPGRADING.md`](UPGRADING.md): add any step a product must take when merging (new env key, `set_setting`, migration order).
3. **Bump `VERSION`** (plain `MAJOR.MINOR.PATCH`, currently `0.1.0`).
4. **Regenerate the manifest** — core repository only:

   ```bash
   python3 scripts/core_doctor.py --write     # then:
   python3 scripts/core_doctor.py --verify    # exit 0 = manifest matches the tree
   ```

   This is the "chore(core): regenerate the manifest for …" commit in `git log`. `--write` refuses (exit 2) outside the core repository. Core means the trees listed in `CORE_TREES` / `CORE_FILES` in `scripts/core_doctor.py` (ADR-0010); `documentation/` is **not** core. Exit codes: 0 clean · 1 drift or stale manifest · 2 setup error.
5. **Commit, then tag** `vX.Y.Z` — only after the owner's explicit yes (below).

## The guard: `.github/workflows/core-guard.yml`

| Where | On a PR / push to `main` |
|---|---|
| Core repository (`CORE_REPOSITORY`) | A PR touching core files must also change `core.manifest.json`; `--verify` must pass |
| A product | A PR touching core files fails unless labelled `core-change`; `scripts/core_doctor.py` runs on the whole tree |

Role is chosen by repository name, never a template flag. A setup error (no manifest, no `VERSION`) is never excused by the label.

## Commit and approval rule

Never commit or push without the owner's explicit yes, every time (`AGENTS.md` § 1 rule 1). Conventional commits `type(scope): description`; **no AI attribution** trailer. Stage by path, never `git add -A`. `.claude/hooks/agent_guard.py` enforces the commit checks (`python3 .claude/hooks/test_agent_guard.py`). Never name another codebase in a message or doc (rule 5a).

## Releasing a product built on this

Not this doc's job beyond the commands below. A product deploys by tag with its own versioning: [`system-design/OPERATIONS.md`](system-design/OPERATIONS.md) § 5 release images, § 6 deploy driver, § 19 git flow; [`system-design/DEPLOYMENT.md`](system-design/DEPLOYMENT.md) § 2 (§ 0: the topology is written, not proven). Taking a core update: [`UPGRADING.md`](UPGRADING.md). Diagnosing it afterwards: [`PRODUCTION.md`](PRODUCTION.md).

- **Deploy:** `python3 scripts/deploy.py <version> --env production --current-version <old> --swap-cmd "<restart command>" --health-url <ready url>`. Other flags: `--swap-cmd` (repeatable), `--health-tries`, `--health-interval`, `--backup-dir`, `--no-backup` (refused outside development), `--dry-run` (prints the plan). The backup runs before `migrate`; a failed backup ends the deploy. Exit codes: 0 deployed, 2 configuration, 3 backup failed, 4 migrate failed, 5 swap failed, 6 health check failed, 7 validation failed.
- **Rollback:** re-run with the previous version (migrations are expand-only). Restoring the database is the last resort.
- **Backups:** `manage.py backup [--label L] [--dir D]` writes a verified dump. `manage.py restore DUMP --yes` restores; a dump from another environment comes up with schedules, webhooks and notification routes off, and `manage.py restore --reenable <config_snapshot file>` turns them back on. See [`PRODUCTION.md`](PRODUCTION.md) § Backup and restore.
- **Images:** `backend/Dockerfile.prod` and `frontend/Dockerfile.prod` (build from the repository root; the build commands are in each file's header) and `docker-compose.prod.yml` (application tier only; no edge proxy yet, DB-118; `gunicorn` must be added to `pyproject.toml`, DB-116).

## Rollback — what is possible today

| Case | Today |
|---|---|
| A bad core commit, not yet released | `git revert` it (owner approves), then regenerate the manifest and `--verify` |
| A bad released core version | Cut a new PATCH forward. No tag exists yet, so there is no tagged rollback target |
| A product that took a bad update | It reverts its own merge commit on its branch; `python3 scripts/core_doctor.py` then shows the drift |
| Migrations | Core migrations are never squashed or renamed once a product exists; rollback by "previous tag" is only valid for expand/contract migrations (`OPERATIONS.md` § 6, § 8) |
| Image / deploy rollback ("re-run with the previous tag") | Re-run `scripts/deploy.py` with the previous version (built in 9.5; not exercised against a real deploy) |
