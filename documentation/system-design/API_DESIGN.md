# API Design

**The contract between the Django API and every client.** One shape, decided once — the frontend
writes one error handler and one pagination reader instead of one per endpoint.

> ⚠️ Partly built: pagination, throttling, `IsAuthenticated` and the OpenAPI schema are configured in
> `config/settings.py`. The envelope, error shape and filtering conventions below are design.

---

## URLs

```
/api/<module>/<resource>/            list, create
/api/<module>/<resource>/<id>/       retrieve, update, delete
/api/<module>/<resource>/<id>/<action>/   a verb that is not CRUD
```

| Rule | Note |
|------|------|
| Plural, lowercase, kebab-case | `/api/core/api-consumers/` |
| **Trailing slash** | Django's default. Be consistent or `APPEND_SLASH` surprises you on POST |
| Module-prefixed | Plugin routes are `/api/<plugin>/…` — the prefix is the plugin name |
| Nouns, not verbs | `POST /quotes/5/approve/` is the exception, and it is deliberate |

**No `/v1/` for now.** A version in the path is a promise to maintain two code paths, and there are
no external consumers yet. When the first one arrives, add `/api/v1/` **and write the ADR** — the
mistake is adding it early and never using it, so it becomes decoration everyone must type.

---

## Responses

### Success

Return the resource, unwrapped. **No `{"success": true, "data": …}` envelope** — HTTP status already
says whether it worked, and an envelope makes every client unwrap before use.

```jsonc
// GET /api/core/users/42/
{ "id": 42, "email": "a@example.com", "name": "Ayush", "created_at": "2026-09-16T09:00:00Z" }
```

### Lists — always paginated

`PageNumberPagination`, `PAGE_SIZE: 20`, already configured.

```jsonc
{ "count": 137, "next": "…?page=3", "previous": "…?page=1", "results": [ … ] }
```

**Never disable pagination on a list that can grow.** A list endpoint that returns everything is fine
with 50 rows and an outage at 500,000.

### Errors — one shape

DRF's default error body varies by exception type, which means the frontend needs several handlers.
Normalise it with a custom exception handler:

```jsonc
{
  "error": {
    "code": "validation_error",
    "message": "This request could not be processed.",
    "fields": { "email": ["A user with this email already exists."] }
  }
}
```

| Status | When |
|--------|------|
| `400` | Validation failed — `fields` populated |
| `401` | Not authenticated |
| `403` | Authenticated, not permitted |
| `404` | Not found, **or found but not visible to this user** |
| `409` | Conflict — a real state clash, not a validation error |
| `429` | Throttled |
| `500` | Unhandled. **Never leak the exception** |

> **Why 404 and not 403 for an invisible row:** a 403 confirms the row exists. Distinguishing them
> tells an attacker which ids are real. `visible_to()` returning nothing naturally produces a 404 —
> so the safe behaviour is the one you get by default, which is how it should be.

---

## Requests

- **Validate in the serializer** (`validate_<field>`, `validate`), never in the view
- **Never trust `request.data` for ownership.** A `user`, `owner` or `organisation` field comes from
  `request.user` — never the payload. **This is the most common DRF authorization bug**
- `PATCH` for partial updates, `PUT` for full replacement. Prefer `PATCH`
- Reject unknown fields rather than ignoring them, so a client's typo is visible

---

## Filtering, searching, ordering

Consistent query parameters across every list endpoint:

```
?search=ayush           free text, over serializer-declared fields
?ordering=-created_at   allow-listed fields only
?is_active=true         exact-match filters, allow-listed
?page=2&page_size=50    page_size capped server-side
```

**Allow-list, never pass through.** A filter parameter mapped straight into `.filter(**params)` lets
a caller filter on `password` or traverse a relation to another tenant's rows. Declare the permitted
fields explicitly.

**Cap `page_size`.** Uncapped, it is a denial-of-service parameter.

---

## Authentication

Whatever [`../planning/AUTH_RND.md`](../planning/AUTH_RND.md) decides (`TECH_DEBT` DB-1). Regardless:

- `/api/auth/me/` returns the user **and their permission codes** — one round trip for the shell
- Wrong password and unknown email answer **identically**, so the endpoint is not a user oracle
- Auth endpoints are throttled harder than the rest

---

## Machine callers

Plugins and integrations get credentials, not user accounts. Key points, taken from how the
reference projects do it:

- Rate-limit **per credential**, not per IP. Several consumers behind one NAT otherwise share a
  budget, and one noisy integration starves the others
- A machine caller is a **principal** with permissions, checked by the same RBAC layer. Do not build
  a second authorization system for API keys
- Credentials are **hashed at rest** and shown once at creation

---

## Documentation

drf-spectacular generates `/api/schema/`; Swagger UI is at `/api/docs/`.

- Non-obvious endpoints get `@extend_schema`. **A wrong schema is worse than none**
- The committed schema must match the routes — CI should fail on drift, because the frontend's types
  are generated from it (`TECH_DEBT` **DB-4**) and a stale schema types the frontend against
  yesterday's API while passing every check

---

## Checklist for a new endpoint

- [ ] URL matches the pattern; module-prefixed; trailing slash
- [ ] `permission_classes` set — entity-level (Layer 1)
- [ ] Queryset goes through `visible_to()` — object-level (Layer 2)
- [ ] Ownership fields come from `request.user`, never the payload
- [ ] List is paginated; filters and ordering are allow-listed
- [ ] Errors raised as DRF exceptions, not hand-built responses
- [ ] Appears correctly in `/api/schema/`
- [ ] A test proves an anonymous caller gets 401/403 and an unpermitted user gets 403
