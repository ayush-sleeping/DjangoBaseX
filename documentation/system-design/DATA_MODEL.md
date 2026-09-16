# Data Model

**The core's entities, and the conventions every model follows.**

> ⚠️ **Nothing here is built yet** — `backend/core/models.py` is empty and the only tables are
> Django's own. This is the design to build against, and it is the **most expensive document in the
> repository to get wrong**: a schema decision made by accident on the first migration is paid for by
> every product ever copied from this core.
>
> **Five decisions below are marked 🚧. Do not write the first migration until they are ADRs.**

---

## 1. 🚧 The five decisions

Each is cheap now and painful later. They are listed in order of how expensive the retrofit is.

### 🚧 D1 — Custom `User` model, or Django's?

**Must be settled before ANY migration references `AUTH_USER_MODEL`.** Django's own docs call
changing it later "significantly more difficult"; in practice it means a manual data migration
across every table with a user foreign key.

**Recommendation: add `core.User(AbstractUser)` now, empty.** It costs one migration today and
cannot be added cheaply at product three. An empty subclass is not over-engineering — it is the
option value.

Also decide now: **is the login identifier an email or a username?** Django defaults to username; a
modern back office almost always wants email. Changing it later means a data migration plus every
auth screen. *Recommendation: email, with `USERNAME_FIELD = "email"` and username removed.*

Tracked as `TECH_DEBT` **DB-10**. This is `BUILD_ORDER` task 1.1.

### 🚧 D2 — Primary keys: `BigAutoField` or `UUID`?

Currently `BigAutoField` (Django's default, set in `settings.py`). Changing the PK type after data
exists is among the worst migrations there is.

| | `BigAutoField` | `UUIDv7` |
|---|---|---|
| Readability | `/users/42/` — easy to talk about | opaque |
| Index size / join speed | smaller, faster | larger |
| **Leaks business volume** | **yes** — `/users/42/` tells a competitor you have 42 users | no |
| Enumerable by an attacker | yes — `/quotes/1`, `/quotes/2`… | no |
| Generated before insert | no | yes — useful for offline clients and idempotency |

**Recommendation: `BigAutoField` for core tables, and treat the enumeration risk as an
authorization problem, not an identifier problem.** If a route leaks data by guessing an id, the
object-level permission is missing — a UUID would only hide the bug. Revisit per-model if a product
exposes public URLs where volume leakage matters.

### 🚧 D3 — Is there multi-tenancy in the core?

**The most structural of the five.** Do rows belong to an `Organisation`, or only to a `User`?

- **Yes** — every product inherits an `Organisation` model and a scoping layer, and every query must
  be scoped. Products that do not need it carry it anyway
- **No** — a product needing tenancy adds it, touching every table it already has. This is a rewrite,
  not a migration

**Recommendation: no organisation model in the core, but design for it.** Specifically: put scoping
behind a **queryset method** (`Model.objects.visible_to(user)`) from the very first module, so a
product adding tenancy changes *one method per model* rather than every view. Record that this is the
reason the method exists, or someone will "simplify" it away.

> If you know today that products will be multi-tenant, choose yes and pay the cost up front —
> retrofitting tenancy is the single most expensive thing on this page.

### 🚧 D4 — Soft delete, or hard delete?

Both reference projects ship a **recycle bin**, which implies soft delete.

**Recommendation: soft delete on user-facing content, hard delete on join tables and logs.** Blanket
soft delete is a trap — every query needs the filter, and one forgotten `.filter(deleted_at=None)`
silently shows deleted rows. Use a **default manager that excludes soft-deleted rows**, with
`all_objects` for the few places that need them, so forgetting is the safe direction.

Also decide the **retention rule**: a recycle bin nobody empties is an unbounded table and a
GDPR problem.

### 🚧 D5 — How is change history recorded?

| Option | Cost | Gives you |
|--------|------|-----------|
| `created_by` / `updated_by` columns | trivial | who touched it last |
| An `ActivityLog` table (what/who/when/where) | small | an audit trail and an activity feed |
| `django-simple-history` (a shadow table per model) | real storage cost | full row-level history and rollback |

**Recommendation: both of the first two.** Stamp columns on the base model, plus one `ActivityLog`
table. Add `simple-history` per model, only where a product needs to see previous values — the
roadmap lists it, but applying it to every model is a storage decision, not a default.

---

## 2. The base models

Assuming the recommendations above, everything inherits from these. They live in `core/models/base.py`.

```python
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuthoredModel(TimeStampedModel):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        abstract = True


class SoftDeletableModel(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = NotDeletedManager()      # default EXCLUDES soft-deleted rows
    all_objects = models.Manager()     # explicit opt-in to see them

    class Meta:
        abstract = True
```

> **Why `on_delete=SET_NULL` and `related_name="+"` on the stamp columns:** deleting a user must not
> cascade away every row they ever created, and reverse accessors from `User` to every model in the
> system would be noise. Getting `on_delete` wrong here is silent, catastrophic data loss.

---

## 3. Core entities

**Phase 1 — the minimum a back office needs.** Everything else is a plugin or a later phase.

| Model | Purpose | Key fields | Notes |
|-------|---------|-----------|-------|
| `User` | Identity | email (unique, the login), name, is_active, is_staff | D1. Email is the identifier |
| `Role` | A named bundle of permissions | name, slug, description, is_system | `is_system` roles cannot be deleted |
| `Permission` | One capability | code (`module.feature.action`), label, group | **Registered in code, seeded to DB** — see [`RBAC_DESIGN.md`](RBAC_DESIGN.md) |
| `PermissionGroup` | UI grouping | name, module, order | So the roles screen is readable |
| `UserRole` | User ↔ Role | user, role | Explicit table; a user may hold several |
| `Setting` | Runtime configuration | key, value, type, is_public | DB-backed, so non-developers can change it |
| `ActivityLog` | Audit trail | actor, verb, target (generic FK), meta, ip, at | D5. Append-only — **never updated or deleted** |
| `Invitation` | Onboarding | email, role, token, expires_at, accepted_at | Token is **hashed at rest**, like a password |
| `Session` | Active logins | user, token_id, ip, user_agent, last_seen, revoked_at | Needed for "sign out everywhere" and immediate revocation |

**Phase 2+, as needed:** `ApiConsumer` + `ApiCredential` (machine callers), `FeatureFlag`,
`Webhook` + `WebhookDelivery`, `SearchableEntity`, `Notification`, `Attachment`.

> Deliberately **not** in the core: anything a product would name. No `Client`, no `Order`, no
> `Ticket`. If you are adding a model and can name the industry it belongs to, it is product or
> plugin code ([`../VISION.md`](../VISION.md) § What DjangoBaseX is not).

---

## 4. Naming conventions

| Thing | Rule | Example |
|-------|------|---------|
| Model | Singular, `PascalCase` | `ActivityLog` |
| Table | Set `db_table` **explicitly**; plugin tables prefixed | `core_activity_log`, `billing_quotes` |
| Boolean field | `is_` / `has_` / `can_` | `is_active` |
| Timestamp | `<verb>_at` | `deleted_at`, `accepted_at` |
| Foreign key | Singular noun | `user`, not `user_id` |
| M2M / through | Both nouns | `UserRole` |
| Choices | `TextChoices`, never bare tuples | `class Status(models.TextChoices)` |

**Hard rules**
- **Never `null=True` on a `CharField`/`TextField`.** Use `blank=True` + `""`. Two representations of
  "no value" is a permanent source of bugs
- **Explicit `on_delete` on every FK.** Ruff's `DJ` rules enforce it; *think* about the answer
- **`__str__` on every model.** Also a `DJ` rule, and it is what makes the admin usable
- **Constraints in the database** via `Meta.constraints` — not only in a serializer. Serializers are
  bypassed by the admin, the shell, management commands and data migrations
- **Index what you filter on**, especially `created_at`, `deleted_at` and every FK used in a scoped query

---

## 5. The scoping rule

Every model that a non-superuser can list exposes:

```python
class EnquiryQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The rows this user may see. Fails CLOSED: unknown → nothing."""
```

**Why this is mandatory from module one, even with no tenancy (D3):**

1. It is the single place scoping lives, so it can be **tested once per model**
2. It **fails closed** — a new role with no rule sees nothing, rather than everything
3. If the product ever adds organisations, tenancy is **one method per model**, not every view

A view that calls `.filter()` directly instead of `.visible_to()` has opted out of authorization
without anyone noticing. Treat it as a review blocker.

---

## 6. Before the first migration — checklist

- [ ] D1 decided and an ADR written; `AUTH_USER_MODEL` set if custom
- [ ] D2 decided and recorded (even if the answer is "keep the default")
- [ ] D3 decided — and if "no", the `visible_to()` rule is documented as the reason
- [ ] D4 decided; base models written if soft delete is in
- [ ] D5 decided; stamp columns on the base model
- [ ] `core/models/base.py` exists and the first real model inherits from it
- [ ] `makemigrations` output **read**, not just run

> The first migration is the one nobody can undo cheaply. Spend the hour.
