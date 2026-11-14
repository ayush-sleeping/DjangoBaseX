# DjangoBaseX — diagnosing a running instance

> **Status:** Hub — checked 2026-11-14 · DjangoBaseX has **no production deployment of its own** and no production topology yet (`system-design/DEPLOYMENT.md` § 0). This doc is the diagnostic surface every product copied from it inherits: request ids, structured logs, three health rungs, `manage.py doctor`. Sentry is decided (ADR-0013) but not built.

Read-only checks only. Never write to a live database or queue from a debugging session. Context: [`PURPOSE.md`](PURPOSE.md), [`INVARIANTS.md`](INVARIANTS.md).

## What runs

| Process | Source | Notes |
|---|---|---|
| Django API | `backend/` (`manage.py runserver` in the dev compose) | Production server (Gunicorn/Uvicorn) is 🔜 — `DEPLOYMENT.md` § 0 blocker 3 |
| Next.js frontend | `frontend/` (`next dev` in compose) | `npm run build` + `npm run start` for production (`DEPLOYMENT.md` § 2) |
| Celery worker | `docker-compose.yml` `worker`, `-Q default,bulk,outbox` | A queue nobody consumes never runs and nothing raises |
| Celery beat | compose `--profile scheduler` | Exactly one; two double every scheduled job |
| Redis | compose `redis` | Cache (throttles, lockout, session liveness) and broker (db 1) |
| Database | compose `db` (PostgreSQL 16); plain host `runserver` uses SQLite | ADR-0005 |

## Health: three rungs

Defined in `backend/core/observability/health.py`; routes in `backend/core/urls.py` (under the API prefix).

| URL | Rung | Checks | Answers |
|---|---|---|---|
| `/api/health/` and `/api/health/live/` | live | No I/O. Is the process worth keeping? | 200 |
| `/api/health/ready/` | ready | Database + cache, bounded by client timeouts. Names the failed dependency (`database` / `cache`), never exception text | 200 / 503 |
| `/api/health/components/` | components | Every registered probe; needs permission `core.health.view` | ok 200 · degraded 200 · down 503 |

Only a *critical* component can make the install `down`. The `jobs` probe is non-critical: a stopped worker shows `degraded`, never ejects the web tier. Live and ready bypass sessions, CSRF, auth and throttling (`HealthShortCircuitMiddleware`). Spec: `system-design/OBSERVABILITY.md` § 6.

## `manage.py doctor`

```bash
cd backend && uv run python manage.py doctor [--json] [--only k,…] [--skip k,…] [--strict] [--fatal-only]
```

Exit `0` clean · `1` a failure · `2` a doctor itself crashed (not a pass) · `3` usage error. Registered doctors (`backend/core/apps.py`, `backend/core/outbox/jobs.py`):

| Key | What it means when it fails |
|---|---|
| `dataplane` | A required row is missing or odd (e.g. no active superuser, no administrator role). `manage.py dataplane` is the older entry |
| `queue` | Celery settings wrong, a stalled queue, a queue with no consumer, dead or unregistered task names in Redis |
| `schedule` | Beat out of sync with the job registry, or a scheduled job failing, overdue or never run |
| `outbox` | Outbox rows stuck (no worker on queue `outbox`), unregistered topic, leases `core.outbox_recover` has not picked up, unknown/failed rows awaiting a human |

Not built: `permissions`, `migrations`, `settings`, `observability`, `connections`, `retention`, `plugins`, `search`, `docs` (`OBSERVABILITY.md` § 12). Also read-only and useful: `python -m core.config_audit` (production-safety audit), `manage.py check --deploy`, `manage.py sync_schedules --dry-run`.

## Logs and one request

- **Format:** JSON when `LOG_FORMAT=json` (enforced when `APP_ENV` is production-like), console otherwise; level `LOG_LEVEL`. Built in `backend/core/observability/logging.py`; JSON escapes newlines so a log line cannot be forged.
- **Request id:** `RequestIdMiddleware` (`backend/core/observability/request_id.py`) sets one id per request, returned in the `X-Request-ID` header and in the error envelope `error.request_id`. A caller's id is trusted only when `TRUSTED_PROXY_COUNT > 0`; otherwise it is kept as `client_request_id`.
- **Scrubber:** one, `backend/core/observability/scrub.py`, applied to every log record (and, per ADR-0013, to Sentry events when built).
- **Following a request:** the frontend shows `request_id` on a failed panel (`frontend/src/core/components/PanelError.tsx`, "reference"). Ask the user for it, then filter backend JSON logs on that id. Spec: `OBSERVABILITY.md` §§ 1–3.

## Errors, jobs, outbox

- **Sentry (ADR-0013):** the only error tracker; optional, enabled by `SENTRY_DSN`. 🔜 **Not built** — no `core/observability/sentry.py`, no code reads `SENTRY_DSN` today. Until it lands, logs are the error record. Do not build a table-based tracker (`OBSERVABILITY.md` § 5 is not built).
- **Job-run monitor:** every job run is recorded by `backend/core/jobs/recorder.py` (own `monitor` DB alias, `JOBS_AND_INTEGRATIONS.md` § 7). Thresholds are runtime settings `operations.queue.stall_threshold_minutes` and `operations.queue.worker_seen_window_minutes` (default 15 each). Read it through the `jobs` health probe and `doctor --only queue,schedule`.
- **Outbox stuck check:** `doctor --only outbox` (finding codes `outbox.stuck`, `outbox.recovery_stalled`, `outbox.unregistered_topic`). Fix named in the finding: start a worker consuming `outbox`, check `core.outbox_drain` runs.

## User reports X — look here first

| Report | Look first |
|---|---|
| Login fails | `system-design/AUTH_FAILURE_MODES.md`; lockout/throttle live in Redis (`/api/health/ready/` cache); `TRUSTED_PROXY_COUNT` wrong behind a proxy locks everyone out (`DEPLOYMENT.md` § 1); log lines for the request id |
| 403 on a page/API | The permission code in the response; `registry` default-deny (`SECURITY.md`, `RBAC_DESIGN.md`); `doctor --only dataplane` for a missing administrator role |
| Blank page | Browser console and `request_id`; backend 5xx for `/api/me/bootstrap/`; `TRAPS.md` Frontend rows; `NEXT_PUBLIC_API_URL` is baked at build time |
| Menu empty / `/api/me/navigation/` 5xx | `manage.py check` for `dbx.E009` (a nav item gated on a permission no app declares — the navigation registry fails closed for everyone); the most recently installed plugin's `wiring.py`; [`TRAPS.md`](system-design/TRAPS.md) Backend |
| Job did not run | `doctor --only queue,schedule`; `/api/health/components/` `jobs`; is a worker consuming that queue and exactly one beat running (`DEPLOYMENT.md` § 2) |
| Email not sent | Outbox first: `doctor --only outbox`; then the worker on queue `outbox`; outside production every message goes only to `NONPROD_TEST_RECIPIENT`, and with none set only console/file backends send (`backend/core/mail/backends.py`, `GuardedEmailBackend`) |
| Wrong number | Reproduce with the same role and data; check the figure's formatter and empty/zero handling (`OBSERVABILITY.md` § 11); locale from bootstrap `localization`; then [`TRAPS.md`](system-design/TRAPS.md) |

See also [`system-design/OBSERVABILITY.md`](system-design/OBSERVABILITY.md), [`system-design/OPERATIONS.md`](system-design/OPERATIONS.md) (§ 6 deploy driver, § 9 backups: designed, tooling is BUILD_ORDER 9.5 🔜), [`system-design/DEPLOYMENT.md`](system-design/DEPLOYMENT.md) § 3 health checks, [`TESTING.md`](TESTING.md), [`SECURITY.md`](SECURITY.md).
