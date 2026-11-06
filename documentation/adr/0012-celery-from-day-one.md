# ADR-0012: Celery and beat run registered jobs from the first job onward

**Status:** Accepted
**Date:** 2026-11-06

## Context

`JOBS_AND_INTEGRATIONS.md` § 2 planned two runners behind one job registry: an in-process
`manage.py run_worker` loop first, with Celery worker + beat arriving later, once real background work
(fan-out, queues, user-triggered tasks) appeared. `PLATFORM_BLUEPRINT.md` § 6 left the choice open as
pending decision #3: *Celery from day one, or an in-process worker first*.

The pressure is `TECH_DEBT` **DB-16**: `auth_cleanup` has no scheduler, so retention depends on a
crontab line the deployer has to remember. BUILD_ORDER 7.1 closes it. Phase 7 then builds the outbox,
webhooks, notifications and ops alerting, and all of them need queued, retried, user-triggered work, not
just periodic sweeps. Redis is already in the development stack (`docker-compose.yml`) as the cache.

## Decision

We use Celery with `django-celery-beat` as the job runner from BUILD_ORDER 7.1 onward, with no
in-process runner built first. Jobs are declared once in the registry, beat schedules are synced from
it, and Celery tasks are generated from each `JobSpec`, configured as `JOBS_AND_INTEGRATIONS.md` § 3
specifies. The broker is the Redis the stack already runs. The registry, the run record and the health
model stay runner-agnostic, so an in-process fallback can still be added later if a product has to run
without a broker. Building one is not part of 7.1.

## Consequences

- **Easier:** Phase 7 (outbox, webhooks, notifications, alerting) builds on the real queue semantics
  (acks, visibility timeouts, routing, time limits) instead of an interim loop that would be replaced.
  The § 3 configuration invariants are enforced and tested from the first job onward.
- **Easier:** One runner to document, monitor and test, not two sharing everything but the loop.
- **Harder:** Every deployment now runs two more processes (worker and beat) and needs a reachable
  broker. A product that wanted to start with just a web process and a cron line can't.
- **Harder:** New dependencies (`celery`, `django-celery-beat`) and their upgrade cadence become part
  of the core every product inherits.
- **Harder:** Local development and CI must either run a worker or exercise tasks without eager mode
  (which § 3 forbids outside tests), so the test strategy for jobs has to be deliberate.

## Alternatives considered

| Option | Why not |
|--------|---------|
| In-process `run_worker` first, Celery later | Cheaper for three daily sweeps, but Phase 7 needs queues and user-triggered work immediately after. The interim loop would be built and then become the less-tested second path |
| Cron line per job, no runner | This is how DB-16 happened: a requirement nothing enforces, and functions nobody calls |
| A lighter queue (RQ, Dramatiq, Huey) | Less ecosystem for beat-style scheduling with database-held schedules, and the specs (§ 3, § 6, § 7) are already written against Celery's semantics |
