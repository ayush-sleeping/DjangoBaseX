# Notes: the example plugin

The acceptance test for the plugin seam (BUILD_ORDER 3.4). It is a real, deliberately small
feature that walks the whole path: **model → migration → permission → API route → nav entry →
frontend page**. It was generated with `scripts/plugins.py new notes`, then grown by hand.

It is **never loaded by the boilerplate**. CI copies it into `backend/plugins/notes/`, links its
frontend half, and runs every check again with it installed (`.github/workflows/ci.yml`). A
product deletes `examples/` or keeps it as a reference; it is not a dependency.

## Try it locally

From the repository root:

```bash
cp -R examples/plugins/notes backend/plugins/notes
cd backend
uv run python ../scripts/plugins.py link notes    # symlink + regenerate the frontend registry
uv run python manage.py migrate
uv run pytest plugins/notes                       # the plugin's own tests
```

Give a role `notes.notes.view` (plus `create` / `delete`), sign in, and the home page lists
**Notes**, which opens `/notes`. To remove it: delete `backend/plugins/notes/` and
`frontend/src/plugins/notes`, then run `uv run python ../scripts/plugins.py registry`.
Its `notes_note` table stays in your database until you drop it.

## What it owns

| Thing | Prefix | Here |
|-------|--------|------|
| Database tables | `notes_` | `notes_note` (`Meta.db_table` explicit) |
| Permissions | `notes.` | `notes.notes.view`, `.create`, `.delete` |
| API routes | `/api/notes/` | list/create, retrieve/delete (URL names `notes:`) |
| Frontend routes | `/notes` | `frontend/notes-page.tsx` |

## What it demonstrates

- `Note.objects.visible_to(user)`: fails closed, so a person sees only their own notes
  ([ADR-0011](../../../documentation/adr/0011-no-organisation-in-core.md)).
- Thin views over `services.py`, serializers that only shape, and one code per action.
- `wiring.py` registers the permission group, the API mount and the nav section. Core names none
  of them.
- The frontend half imports `@/core/…` and its own files only (enforced by ESLint), and gates each
  control on the exact code its endpoint enforces.
