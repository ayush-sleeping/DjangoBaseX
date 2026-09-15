# Database & Migrations

**Migrations are the one part of a Django project where a mistake is expensive and delayed.** A bad
model change passes every local check and fails on someone else's machine, or on deploy, with data
already in the table.

---

## The database

SQLite by default; PostgreSQL by setting `DATABASE_URL`
([ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)). One line in `config/settings.py`:

```python
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
```

```bash
# .env — switch to PostgreSQL, no code change
DATABASE_URL=postgres://user:password@localhost:5432/djangobasex
```

> ⚠️ **SQLite is a development convenience, not a deployment target.** It differs from PostgreSQL in
> ways that bite: constraint enforcement timing, `JSONField` operator support, no concurrent writers,
> and `django.contrib.postgres` fields (`ArrayField`, `HStoreField`) that do not exist at all.
> **Nothing currently catches a Postgres-only feature that works locally** — no tests, no CI. If your
> change touches Postgres-specific behaviour, set `DATABASE_URL` and develop against Postgres.

`db.sqlite3` is gitignored. Never commit it — it would ship your local rows to every copy of this
boilerplate.

---

## The routine

```bash
cd backend
uv run python manage.py makemigrations          # after editing models
uv run python manage.py migrate                 # apply
uv run python manage.py showmigrations          # what's applied
uv run python manage.py sqlmigrate <app> 0002   # the SQL it will run — read it
```

### Rules

1. **Every model change gets a migration, in the same commit as the model change.** Not the next
   commit. A model without its migration passes `manage.py check`, passes Ruff, and breaks for
   everyone else.
2. **Verify with `--check` before you call it done:**
   ```bash
   uv run python manage.py makemigrations --check --dry-run
   ```
   Non-zero exit means a model change has no migration. This is in the `AGENTS.md` § 2 gate.
3. **Read the generated migration.** Django guesses on renames and it guesses wrong often enough to
   matter — a rename it reads as drop+create is silent data loss.
4. **Run `sqlmigrate` for anything touching an existing table** with data in it.
5. **Never edit an applied migration.** Write a new one. Editing one that has run on another machine
   leaves the two databases permanently divergent with no error.
6. **Never delete migration files** to "clean up". The chain is the history; a gap is unrecoverable
   for anyone who already migrated.
7. **One migration chain per app, one head.** A branched chain is silent until `migrate` runs — which
   on a deploy is the worst possible moment to discover it. See *Merge conflicts* below.
8. **Migrations are excluded from Ruff** (`exclude = ["migrations"]`). Do not reformat them; it makes
   every future diff noisy.

---

## Adding a non-nullable field to a populated table

The case that actually causes outages. Django will prompt for a one-off default, and accepting that
prompt writes a migration that is wrong for production. Do it in **three migrations**:

1. Add the field as `null=True` (or with a default) — deploy
2. A **data migration** backfilling existing rows — deploy
3. Flip to `null=False` — deploy

One migration doing all three locks the table for the duration of the backfill, and on a large table
that is downtime.

For a **data migration**, use `RunPython` with a reverse function, and access models via
`apps.get_model("app", "Model")` — never by importing them. An imported model is the *current* one;
a historical migration must see the schema as it was:

```python
def backfill(apps, schema_editor):
    Enquiry = apps.get_model("enquiries", "Enquiry")     # ✅ historical
    Enquiry.objects.filter(status="").update(status="new")

def reverse(apps, schema_editor):
    pass   # explicitly a no-op, so the migration is reversible
```

---

## Merge conflicts in migrations

Two branches each adding a migration to the same app produce two heads. `makemigrations --check`
catches it; `manage.py check` does not.

```bash
uv run python manage.py makemigrations --merge
```

Read what the merge produces. If the two migrations touch the same field, a merge is the wrong answer
— rebase and regenerate one of them instead.

> **This is why `AGENTS.md` § 5 forbids parallel agents generating migrations for the same app.**
> Two workers doing it concurrently produce exactly this, and neither of them sees it.

---

## Resetting local data

Development only, and **ask first** (`AGENTS.md` § 1, rule 4) — it is irreversible:

```bash
cd backend
rm db.sqlite3
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

🔜 There are no seeders or fixtures yet. When there are, this becomes a documented, repeatable
command rather than three ad-hoc steps.
