# DjangoBaseX — traps

> **Status:** Hub — checked 2026-11-14 · 34 real incidents from this repo's own history; the table grows as things bite.

**Add a row the day something bites.** When something 403s, renders blank or shows a wrong number, check here before assuming the code is wrong: most of these fail silently or as a different error. Within each group, ordered by how much time the trap cost (most first). Sources: `DAILY_CHANGES` = [`../DAILY_CHANGES.md`](../DAILY_CHANGES.md) (entry date), `DB-n` = [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md), `AGENTS.md` = [`../../AGENTS.md`](../../AGENTS.md). Related: [`../PRODUCTION.md`](../PRODUCTION.md), [`LESSONS_LEARNED.md`](LESSONS_LEARNED.md) (general lessons), [`../INVARIANTS.md`](../INVARIANTS.md).

## Backend

| Trap | Symptom | Fix | Source |
|---|---|---|---|
| Postgres-only behaviour tested only on SQLite | Green locally, red in CI/deploy: `select_for_update()` is a no-op, audit-log triggers and exclusion constraints do not exist | Develop on the Postgres compose stack; run numbering/ledger/audit tests in the PostgreSQL CI job | DB-29, DB-12 |
| `django_db(transaction=True)` | Teardown `TRUNCATE` refused by the audit log's PostgreSQL trigger; SQLite hides it | Use `django_capture_on_commit_callbacks` | DAILY_CHANGES 2026-11-06 (7.1) |
| Log scrubber missed random tokens in free text | Secrets (22-char, hex, compact UUID) reached logs; measured 100% miss | Two measured bands in `core/observability/scrub.py`; secrets travel by key | DB-51; DAILY_CHANGES 2026-11-06 |
| A queue with no worker, or a beat row naming an unknown task | Jobs never run and nothing raises | Registry-owned schedules; `test_every_queue_has_a_worker`; `manage.py doctor --only queue,schedule` | DAILY_CHANGES 2026-11-06 (7.1, BC-33) |
| Typo'd nav permission code | `/api/me/navigation/` answered 500 on every request; no boot check read it | `dbx.E009` seals every catalog at boot — but it only surfaces in `manage.py check`/`runserver`; a process that skipped the checks still 500s for everyone. Suspect a newly installed plugin's `wiring.py` first | DAILY_CHANGES 2026-10-11 (3.4 review) |
| Plugin import swallowed as "absent" | A broken plugin vanished from the app instead of failing boot | `importable()` skips only a missing module naming the plugin's own package | DB-18 |
| Plugin named `login`, `settings`, … | Silently shadowed by core's static pages | `backend/core/plugins.py` `page_segments()`; `new`/`link`/`registry` refuse such a prefix | DAILY_CHANGES 2026-10-11 (3.4 review) |
| Anonymous throttle keyed on `X-Forwarded-For` | Throttle bypassed by rotating the header (proved by `tests/test_throttle_identity.py`) | `NUM_PROXIES = TRUSTED_PROXY_COUNT`; leave it `0` only with no proxy | DB-30 |
| Cookie authenticator without `authenticate_header()` | Anonymous requests got 403, breaking "401 then refresh once" | Define `authenticate_header()` in `users/authentication.py` | DB-31 |
| `SECRET_KEY` generated with a `$` | django-environ misread the key | Generate with `secrets.token_urlsafe(50)` | DB-25 |
| `__Host-` prefix on a cookie with `Path=/api/` | The prefix contradicts the narrow path, so the cookie cannot be valid | Prefix only when Secure and no shared domain, and then `Path=/` | DB-26 |
| Page navigations cannot see `Path=/api/` cookies | Server cannot tell signed-in from out on a page load | `{prefix}_session` marker cookie, gated by `frontend/src/proxy.ts` | DB-20 |
| Unsafe defaults booting in production | `DEBUG`, placeholder secrets, SQLite, console mail in production | `core/config_audit.py` refuses the boot at settings import | DB-7, DB-19 |
| Trigger SQL with a literal `%` | Migration failed on PostgreSQL only | Build the message without `%` | DAILY_CHANGES 2026-10-24 (6.4) |
| Request id reset in a `finally` | 500 body and access log read `-`; first mutation did not catch it | Do not reset in `finally`; streaming-log test | DAILY_CHANGES 2026-10-11 (6.1) |
| Hex-token scrub rule redacting `request_id` | uuid4-hex request ids would vanish from logs | Caught before shipping; see the entry for how the rule and its test canary were adjusted | DAILY_CHANGES 2026-11-06 (DB-51) |
| A production-like boot on `memory://` broker | Jobs published, nothing consumes | `dbx.jobs.E015` refuses it | DAILY_CHANGES 2026-11-06 (7.1) |

## Frontend

| Trap | Symptom | Fix | Source |
|---|---|---|---|
| `tsc` clean only after a local `next dev` | `LayoutProps` not found on every fresh clone and in CI's first run | `typecheck` is `next typegen && tsc --noEmit` | DAILY_CHANGES 2026-10-11 (typecheck fix) |
| Stale `.next/dev/types/validator.ts` | `npm run typecheck` fails with errors from an old dev server | Move the stale file aside, re-run | DAILY_CHANGES 2026-10-11 (6.1) |
| ESLint skipped symlinked plugin files | `@/project` imported in a plugin passed lint | Lint glob covers plugin symlinks | DAILY_CHANGES 2026-10-11 (3.4) |
| Turbopack refuses a symlinked `node_modules` | "Symlink … points out of the filesystem root" | `frontend/node_modules` must be a real directory inside the repo | DB-36 |
| `NavMenu` treated every failure as "no menu" | A 500 looked like a user with no permissions | Only a 401 means "no menu" | DAILY_CHANGES 2026-10-11 (3.4, BC-42) |
| Translation present but wrong shape | Broken ICU arguments rendered garbled text | Load-time shape check keeps the source copy and warns once | DAILY_CHANGES 2026-11-06 (8.4d) |
| First paint of a plugin page | Blank until its message catalogue loads | Documented; server-side plugin copy deferred | DAILY_CHANGES 2026-11-06 (8.4d) |

## Tooling & agents

| Trap | Symptom | Fix | Source |
|---|---|---|---|
| **Parallel git worktrees each install their own `.venv` and `node_modules` (and `.next`)** | The disk fills (ENOSPC) mid-gate; every command fails, even the tool's own temp files | Remove a worktree as soon as its branch merges; run one gate at a time when free space is under ~10 GB | DAILY_CHANGES 2026-11-14 |
| **`git add <dirs>` misses a changed file outside them, then `git worktree remove --force` discards it** | A commit lands without one edit (here a ratchet test), main goes red, and the edit is lost | After staging, any line in `git status --porcelain` not starting with a staged code blocks the commit; never `--force` a worktree whose status is not empty | DAILY_CHANGES 2026-11-14 (main `13df181` → fixed `c08f7ab`) |
| Docker `node_modules` is an anonymous volume | After a dependency change, the old modules persist | `docker compose up -d --wait --build -V` | DAILY_CHANGES 2026-10-11 (compose note) |
| Host `runserver` and compose share `db.sqlite3` and port 8000 | Both fight over the file and the port | Run one or the other | DAILY_CHANGES 2026-10-11 (compose note) |
| Two stacks on `localhost` share cookie names | They sign each other out (cookies ignore the port) | Per-checkout `AUTH_COOKIE_PREFIX` from `scripts/setup.sh` | `docker-compose.yml` header |
| `npm run build` writes `.next/` | Breaks a running dev server | Run it deliberately, dev server stopped | `AGENTS.md` § 2 |
| `frontend/AGENTS.md` is generated by `next dev` | Hand edits are overwritten | Never hand-edit; commit it with your work; rules go in root `AGENTS.md` or `NEXTJS_STANDARDS.md` | `AGENTS.md` § 1 |
| Next.js 16 is not the Next.js training data knows | `params`/`searchParams` are async, caching defaults changed | Read `frontend/node_modules/next/dist/docs/` for the installed version | `AGENTS.md` § 1 |
| A mutation check that did not apply | "7 passed" proved nothing (Ruff had reflowed the line) | Re-apply by line number and confirm the exact test fails | DAILY_CHANGES 2026-10-11 (1.7) |
| `attribution` in `.claude/settings.json` as booleans | Claude Code rejected the file, attribution never turned off | String values: `""` disables | DAILY_CHANGES 2026-10-11 |
| Postgres password vs an old volume | `POSTGRES_PASSWORD` is read only on first volume creation; a new one is refused | `setup.sh` checks; recreate the volume deliberately | `docker-compose.yml` db service |
| `pg_isready` over the unix socket | Passes against the temporary init server before Postgres is up | Probe over TCP (`-h 127.0.0.1`) | `docker-compose.yml`; DAILY_CHANGES 2026-10-22 (4.1) |
