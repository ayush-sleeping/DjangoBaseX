# code-reviewer memory

Committed and public: patterns and conventions only — never secrets, `.env` values, or the name of any
other codebase, product or client (AGENTS.md § 1 rules 5, 5a, 6).

## Patterns seen

- `core/registry.py` catalogs seal on first read. Only `api_routes` (config/urls.py) and `public_routes`
  (dbx.E007) are read at boot. Any catalog with a cross-catalog check in `seal()` (navigation checks
  permissions) needs a system check, or its error first shows up at request time as a 500.
- Plugin packages (`djx_<name>`) sit at `backend/plugins/<name>/djx_<name>/`, not at the top level of
  `backend/`. Scans that list first-party packages from `backend/*/__init__.py` (for example
  `test_core_boundary.py`) never see them.
- Registration attribution (`owner()`) uses `sys._getframe(2)`. It is correct only while the plugin
  calls `register()` itself. A core helper that registers on a plugin's behalf would attribute the
  registration to core and switch the lane rules off for it without any error.
- Frontend routing: static `(core)` and `(project)` routes win over the `(plugins)/[plugin]` catch-all.
  Plugin frontend prefixes are not checked against core page segments.
- Review is read-only (git, grep). Verification output comes from the DAILY_CHANGES entry, and the
  report says when a claim was not re-run.

## Recurring issues

- Docstrings and plan tables that claim enforcement ("system checks seal every catalog", "the test
  fails when core imports a plugin") the code does not have. Check each claim against the code.
- `.catch(() => setX([]))` in frontend fetches turns 500s into an empty UI (BC-42).
- Hand-rolled env-file readers (`scripts/lib/envfile.py`) drift from the real readers: check quotes,
  `export KEY=`, and that an absent `APP_ENV` is production-like (fail closed, as `core.env` is).
- Compose dev stack: anonymous volumes (`node_modules`) survive an image rebuild unless `up -V`, and
  `up --wait` failing under `set -e` skips any later timeout/log-dump code in setup scripts.
