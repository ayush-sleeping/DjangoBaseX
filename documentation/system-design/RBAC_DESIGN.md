# Authorization (RBAC) Design

> **Implementing this?** [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) is the build spec — every table,
> column, foreign key, file and function signature. This document is the *policy* and the *why*;
> that one is the *how*.


**How permissions work, and why this shape.** The hardest thing in the core to retrofit, because
every endpoint and every query depends on it.

> ⚠️ **Not built yet.** Today the only authorization is DRF's `IsAuthenticated` default — which is a
> good fail-closed starting point, but it is binary: signed in or not.

---

## The model

Four concepts, deliberately no more.

```
User ──< UserRole >── Role ──< RolePermission >── Permission ──> PermissionGroup
                                                   (code)         (UI grouping only)
```

| Concept | Is | Is not |
|---------|-----|--------|
| **Permission** | One capability, `module.feature.action` | A role. Never assigned to a user directly |
| **Role** | A named bundle of permissions | A job title with logic attached |
| **UserRole** | A user holds a role | — |
| **PermissionGroup** | How the roles screen groups checkboxes | Anything the code branches on |

**A user's permissions are the union of their roles' permissions.** No per-user grants, no denies.

> **Why no per-user overrides:** the moment a user can hold a permission no role grants, "what can
> this person do?" stops being answerable by looking at their roles, and every support conversation
> becomes an investigation. If one person needs something, that is a role.
>
> **Why no explicit denies:** grant-only means the answer is a set union and is order-independent.
> Deny rules turn authorization into a precedence puzzle, and the failure mode is silent
> over-permission.

---

## Permissions live in code, seeded to the database

**This is the central design decision.** A permission is declared in a Python module, in the app
that owns it. A seeder writes the catalog into the `Permission` table.

```python
# core/permissions.py  (or djx_billing/permissions.py for a plugin)
GROUP = PermissionGroup(
    module="users", label="Users", order=10,
    permissions=[
        ("users.users.view",   "View users"),
        ("users.users.create", "Create users"),
        ("users.users.update", "Edit users"),
        ("users.users.delete", "Delete users"),
    ],
)
```

**Why code and not pure database rows:**

| | Code-declared | Database-only |
|---|---|---|
| A typo in a permission name | caught — grep, and the seeder diffs | silent; the check just always fails |
| Code review sees a new capability | yes, in the diff | no |
| Deploys stay in sync | the seeder is idempotent | rows drift per environment |
| Plugin ships its own permissions | naturally, via its registry entry | needs a manual insert |

The DB rows exist so roles can reference them and the UI can render them — **the code is the source
of truth**. A permission removed from code is deactivated by the seeder, never silently orphaned.

### Naming — `<module>.<feature>.<action>`

Always module-prefixed. Never a bare `view` or `create`.

```
users.users.view          core
users.roles.update        core
settings.settings.manage  core
billing.invoices.create        plugin — the prefix IS the plugin name
```

**Enforced by the conventions test:** a plugin's permissions must start with its own name. Without
it, two plugins both declaring `reports.view` silently share a capability.

---

## The two layers of checking

**Both are required.** They answer different questions, and skipping the second is the classic RBAC
bug.

### Layer 1 — entity: *may this user use this feature at all?*

```python
class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [HasPermission("users.users.view")]
```

### Layer 2 — object: *may this user touch **this row**?*

```python
def get_queryset(self):
    return User.objects.visible_to(self.request.user)     # scoping, per DATA_MODEL § 5
```

> ⚠️ **Layer 1 alone is the bug.** `users.users.update` says the user may edit *users*; it does not
> say they may edit *this* user. A route that checks only Layer 1 and then looks up by id from the
> URL lets any permitted user edit any row. **Every list goes through `visible_to()`, and every
> detail route re-checks** — a scoped queryset is the cheapest way to get both.

---

## Fail closed, everywhere

From [`../VISION.md`](../VISION.md) § principle 3 — the default answer is no.

| Situation | Answer |
|-----------|--------|
| No `permission_classes` on a view | denied — DRF's `IsAuthenticated` default, never removed globally |
| Permission code not in the catalog | denied, and **logged as a bug** — it means a typo or a missing seed |
| A role with no permissions | sees nothing |
| `visible_to()` with no rule for this user | returns `.none()`, never `.all()` |
| A new plugin's routes before its seeder runs | denied |

**Test it:** a user holding a role with zero permissions must be refused by **every** gated endpoint.
That single test catches most accidental openness.

---

## The superuser question

**One `is_superuser` flag that bypasses every check**, exactly as Django does it. Do not invent a
second god-mode.

- Superusers are **created by CLI only**, never through the UI — an escalation path through a web
  form is the bug you cannot take back
- **Superuser actions are still logged** to `ActivityLog`. Bypassing authorization must not mean
  bypassing accountability
- A production install should have very few. Real work is done through roles

---

## Seeded roles

The seeder creates these as `is_system=True` (undeletable) and **idempotently** — running it twice
changes nothing.

| Role | Holds | Note |
|------|-------|------|
| `admin` | every permission, including plugins' | Recomputed as plugins are added |
| `staff` | read everything, write nothing | A safe default for a new employee |

Products add their own. Keep the core's list this short — a core role a product does not want is a
role they have to explain to their users.

---

## How a plugin contributes

The whole integration is one registry call in `AppConfig.ready()`:

```python
registry.permissions.register(permissions.GROUP)
```

Core assembles the catalog from every registration. **Core never names a plugin**, and deleting a
plugin removes its permissions from the catalog on the next boot and seed.

---

## Frontend

The API returns the current user's permission codes on `/me`. The frontend uses them **only to hide
UI** — never as the authorization decision.

```tsx
{can("users.users.delete") && <DeleteButton />}
```

> Hiding a button is a courtesy, not a control. **Every check is enforced server-side**, and an
> endpoint that relies on the button being hidden is unprotected. Assume the client is hostile.

---

## Build order

1. `Permission`, `PermissionGroup`, `Role`, `UserRole` models
2. The code-declared catalog + an idempotent seeder
3. `HasPermission` DRF permission class
4. `visible_to()` on the first model, with its test
5. `/me` returning permission codes; the `can()` helper
6. The roles admin screen — **last**, because it is the easiest part and the one most likely to be
   built first
