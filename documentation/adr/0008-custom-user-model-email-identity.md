# ADR-0008: A custom `users.User`, identified by email, with boolean states

**Status:** Accepted
**Date:** 2026-10-11

## Context

`AUTH_USER_MODEL` has to be settled before any migration refers to it. Changing it afterwards means
a hand-written data migration across every table with a user foreign key, and Django's own
documentation warns against it. The project had no models yet, so the choice was still free. Every
product copied from this boilerplate would inherit whatever is chosen here
(`BUILD_ORDER` 0.1, `TECH_DEBT` DB-10).

The docs gave two different answers. `DATA_MODEL.md` D1 recommended an empty `core.User(AbstractUser)`.
The later and more detailed `AUTH_BLUEPRINT.md` (decisions A1–A3, Ch. 2, § 3.1) put the model in its
own `users` app, because identity and authorization change for different reasons, and `core` must
never import either of them. Both docs agreed that the login identifier should be an email, not a
username.

## Decision

We use a custom user model, `users.User`, in a dedicated `users` app. It subclasses
`AbstractBaseUser` and `PermissionsMixin`, and `AUTH_USER_MODEL = "users.User"`. It has no username:
`USERNAME_FIELD = "email"`, and the email is stored lowercased and unique, with a database check
constraint enforcing the lowercase. User state is held in booleans (`is_active`, `is_staff`,
`is_superuser`), never a free-text status. `is_active` defaults to `False`, so a row created by any
path cannot sign in until something activates it. The column set is `AUTH_BLUEPRINT.md` § 3.1, and
`users/0001_initial` is the first migration in the project (§ 13).

## Consequences

- Products can add fields to the user without the painful swap, because the model is already theirs.
- Email login matches what a back office expects, and changing the identifier later would have meant
  a data migration plus every auth screen.
- **Costs.** We own the manager (`create_user`, `create_superuser`, email normalisation) and the
  admin form, which `AbstractUser` would otherwise provide. Third-party packages that assume a
  `username` field need configuring. `is_active=False` by default means every path that creates a
  user has to activate it deliberately, and `createsuperuser` is the only path that does so today.
- `PermissionsMixin` still brings the `auth_group` and `auth_permission` link tables. The RBAC
  design does not use them (A9). They stay empty until `rbac` replaces `has_perm` (`BUILD_ORDER` 1.2).
- The `has_perm` override that stops superusers bypassing the audit trail (`AUTH_BLUEPRINT.md`
  § 7.4) is **not** in this change. It only matters once `RBACBackend` exists, and it ships with
  that backend and its test in 1.2.
- Any database migrated before this change has to be recreated. The only one was an empty local
  `db.sqlite3`.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Django's built-in `auth.User` | Cheapest today, but the most expensive thing on the list to change later |
| `core.User(AbstractUser)`, empty | Keeps a `username` that email login would have to remove in a later migration, and puts identity in `core`, which `AUTH_BLUEPRINT.md` Ch. 2 keeps free of app models |
| A `status` string instead of booleans | A comparison like `!= "ACTIVE"` turns a typo in any writer into a silent grant |
