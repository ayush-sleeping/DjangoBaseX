# Changelog

All notable changes to the DjangoBaseX core, newest first, with what a product must do to take each one.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[`documentation/ADR.md`](documentation/ADR.md) ADR-0014 (semver for core releases).

- Capabilities by version: [`documentation/VERSION_SUMMARY.md`](documentation/VERSION_SUMMARY.md).
- Step-by-step merge notes: [`documentation/UPGRADING.md`](documentation/UPGRADING.md).
- Per-task detail: [`documentation/DAILY_CHANGES.md`](documentation/DAILY_CHANGES.md).

`VERSION` is `0.1.0` and no section has been tagged yet, so everything shipped so far is under Unreleased.
Each entry is one line and tracks a done mark in [`documentation/planning/BUILD_ORDER.md`](documentation/planning/BUILD_ORDER.md).

## Unreleased

### Added

- **Sign-in**: email and password into `httpOnly` cookie JWTs with rotating refresh tokens, password reset,
  throttling and progressive lockout, TOTP two-factor and re-auth for sensitive actions (1.1).
- **Authorization**: code-declared permission catalog, roles and grants with an audit trail, and a gate that
  denies every endpoint that does not declare its permissions (1.2 to 1.4).
- **Users and the first account**: user CRUD, set-your-password email, invitations and
  `manage.py bootstrap_admin` (1.5, 1.5b).
- **`core/` and `project/` split, plugins**: plugin discovery from `plugin.toml`, `scripts/plugins.py`, an
  example plugin and frontend plugin mounting (1.6, Phase 3).
- **Test suite and CI**: pytest architecture tests, a Vitest suite and `ci.yml` (Phase 2).
- **One-command setup, core drift detection, development Docker stack**: `scripts/setup.sh`,
  `scripts/core_doctor.py` with `core-guard.yml`, and a Compose stack (4.1 to 4.4).
- **Production guard rails**: environment classification with a boot refusal, project identity, the typed settings
  registry, feature flags, vocabularies, locale and currency, encryption service, audit engine, money (Phase 5, 6.3 to 6.5).
- **Observability**: request ids, structured logs with one scrubber, three-rung health checks (6.1, 6.2).
- **Background jobs**: Celery and beat from a job registry, job-run monitor and doctor, outbox, reconcilers and
  locks (7.1 to 7.3).
- **Safe outbound HTTP**: one client factory with private-range refusal, and a non-production guard that
  allow-lists hosts and redirects mail (7.4).
- **Retention engine**: registered policies with age and row caps, `manage.py retention [--status] [--dry-run]` (7.5).
- **Frontend platform**: typed transport and data layer, bootstrap and navigation-as-gate, design system,
  i18n and generated API contracts (8.1 to 8.4).
- **Per-request CSP and runtime brand colours**, Report-Only by default (8.5).
- **Engineering practice** (9.6): a doc link test and generated folder indexes, a PR template carrying
  `BUG_CLASSES.md`, an ADR template with Invariant and Where it bites, this changelog, and `manage.py seed_demo`.

### Upgrade notes

- **7.1**: a deployment needs workers consuming every declared queue and exactly one beat. `auth_cleanup` is no
  longer a cron entry; remove it from crontab.
- **7.3**: add the `outbox` queue to every worker's `-Q`. `LOCKS_REDIS_URL` (optional; defaults to the cache's Redis)
  is where job locks live. Migration `core/0007` adds the outbox and finding tables.
- **7.4**: new env keys `OUTBOUND_ALLOWLIST`, `NONPROD_TEST_RECIPIENT` and `EMAIL_TIMEOUT` (default 10 s). Outside
  `APP_ENV=production` (staging included) outbound HTTP reaches only allow-listed hosts and mail goes to
  `NONPROD_TEST_RECIPIENT`; production must say `APP_ENV=production` exactly. New dependency `httpx`.
- **7.5**: the `*_RETENTION_DAYS` env keys (for example `LOGIN_ATTEMPT_RETENTION_DAYS`) are removed. Windows are the
  runtime settings `retention.<owner>_<name>.days`; set them with `manage.py set_setting` if you had changed a default.
- **8.5**: the frontend reads new optional keys `CSP_MODE` (`off`, `report_only`, `enforce`; default `report_only`),
  `CSP_EXTRA_ORIGINS` and `CSP_REPORT_URL`, at request time: enforcing needs a restart, not a rebuild.
- **9.6**: no env keys, no migrations. `manage.py seed_demo` refuses to run when the environment is production-like
  and prints a random throwaway password once.
- Earlier breaking changes (`REAUTH_*` to runtime settings, `MFA_ENCRYPTION_KEY` to `FIELD_ENCRYPTION_KEYS`, the
  project-identity cookie rename) are listed in [`documentation/VERSION_SUMMARY.md`](documentation/VERSION_SUMMARY.md).
