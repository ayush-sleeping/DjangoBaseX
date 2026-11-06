# ADR-0013: Error tracking is Sentry-only; core builds no error tracker

**Status:** Accepted
**Date:** 2026-11-06

## Context

`OBSERVABILITY.md` § 5 specified a built-in error tracker (Tier 2 core): an errors table, fingerprint
grouping, and a screen for browsing and resolving errors. `PLATFORM_BLUEPRINT.md` § 6 left pending decision
#2 open: *built-in error tracking or Sentry-only*. The core already has structured logs with a request id
and one scrubber that redacts secrets (BUILD_ORDER 6.1), and those are what any error report would be
built from.

## Decision

Error tracking is Sentry, configured by an optional `SENTRY_DSN`, with the shared scrubber applied in
`before_send` and `before_breadcrumb`. Core builds no errors table, no grouping and no error screen.
Without a DSN, a product relies on its structured logs. `OBSERVABILITY.md` § 5 isn't built.

## Consequences

- **Easier:** much less core code to own, secure and migrate. Grouping, alerting, release tracking and
  source maps come from a tool built for them.
- **Easier:** one place to look for errors across the backend and the frontend.
- **Harder:** a product that can't send data to a third party gets only logs, until it adds its own
  tracker or self-hosts Sentry.
- **Harder:** the scrubber must cover everything Sentry sends (events, breadcrumbs, request bodies), and
  a test has to prove it, because a leak there leaves the system.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Built-in tracker (`OBSERVABILITY.md` § 5) | A table, grouping, retention and a screen in every product, rebuilding what mature tools already do |
| Both: a minimal built-in store plus Sentry | Two places to look and two code paths to keep scrubbed; it combines the costs of both |
