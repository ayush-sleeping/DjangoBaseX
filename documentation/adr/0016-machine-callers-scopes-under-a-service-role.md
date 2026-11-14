# ADR-0016: Machine callers hold permission-code scopes under a service-role ceiling

**Status:** Accepted
**Date:** 2026-11-14

**Invariant:** Authorise a machine call only when the token's scopes include the permission code **and** the consumer's service role currently grants it; never let a token be owned by a person, and never invent a second permission vocabulary for machines.

**Where it bites:** A token whose scope list was valid when issued keeps working after its role lost the permission (scope-only check), or a machine is refused with a 403 for a permission a human with the same code would pass (two vocabularies drifting) — both look like ordinary 403/200 responses, not like an authorization bug.

## Context

Machine callers (systems such as "warehouse-sync" or "website-feed") need API tokens. `API_DESIGN.md` said only
that a machine caller is "a principal with permissions", which leaves open whose permissions and how many gates.
`API_PLATFORM.md` § 9 compares the designs. The decision was deferred on 2026-10-11 (TECH_DEBT DB-21) until the first
token endpoint; BUILD_ORDER 9.2 and the webhook endpoint's owner (7.6, DB-79) now need it.

## Decision

A machine caller is an **API consumer** — a row named after a system, never a person — that owns tokens and has a
**machine-owned service role** (`service_role`, a normal RBAC `Role`) as its ceiling. A token's **scopes are
permission codes from the same catalogue** humans use (or `["*"]` = everything the role grants). A request is
allowed only if **both** gates pass: the scope is on the token **and** the service role's live permissions include
it. Scopes are validated at issue time against the catalogue and the role. Revoking a permission from the role, or
deactivating the consumer, takes effect for every token without reissuing them. Details (token format, hashing,
expiry, rotation, audit) follow `API_PLATFORM.md` § 8–9.

## Consequences

- One permission vocabulary, one catalogue, one `test_permission_codes.py`: a new endpoint's code is grantable to
  machines with no extra work.
- Ownership survives staff turnover; audit rows name the consumer, not a person.
- Two checks per machine request (scope and role); the role lookup must be cached like human permissions.
- A token can never exceed its role, so a broad `["*"]` token is still bounded — but an over-granted service role
  is now the thing to review.
- Webhook endpoints gain a nullable `consumer` FK in 9.2 (DB-79).

## Alternatives considered (rejected options, with the reason)

| Option | Why not |
|--------|---------|
| Pure abilities (Design A): tokens carry their own ability list that never satisfies a human permission check | A second vocabulary to name, review and keep in step with every endpoint; machines and humans drift apart |
| Scopes only, no role ceiling | A scope granted once outlives the permission it reflects; there is no single place to cut a machine's access |
| Tokens owned by a user ("personal access tokens") as the machine mechanism | Breaks when the person leaves, or keeps working under a meaningless name; audit rows blame a person for a machine's action. PATs may still be added later as a separate feature (`API_PLATFORM.md` § 9) |
