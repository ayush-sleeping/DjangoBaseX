# Enquiries: the second product

The second product built on the core (BUILD_ORDER 10.1): an enquiries pipeline, a small CRM. It exists
to find what hurts when something other than the reference plugin is built on DjangoBaseX; what hurt is
logged in [`documentation/planning/SECOND_PRODUCT.md`](../../../documentation/planning/SECOND_PRODUCT.md).

It is **never loaded by the boilerplate**. CI copies it into `backend/plugins/enquiries/` beside notes,
links its frontend half, and runs every check again (`.github/workflows/ci.yml`).

## Try it locally

From the repository root:

```bash
cp -R examples/plugins/enquiries backend/plugins/enquiries
cd backend
uv run python ../scripts/plugins.py link enquiries   # symlink + regenerate the frontend registry
uv run python manage.py migrate
uv run pytest plugins/enquiries                      # the plugin's own tests
```

Give a role the `enquiries.enquiries.*` codes, sign in, and the home page lists **Enquiries**, which
opens `/enquiries`. To remove it: delete `backend/plugins/enquiries/` and `frontend/src/plugins/enquiries`,
then run `uv run python ../scripts/plugins.py registry`. Its `enquiries_enquiry` table stays in your
database until you drop it.

## What it owns

| Thing | Prefix | Here |
|-------|--------|------|
| Database tables | `enquiries_` | `enquiries_enquiry` |
| Permissions | `enquiries.` | `enquiries.enquiries.view`, `.create`, `.update`, `.transition`, `.delete` |
| API routes | `/api/enquiries/` | list/create, retrieve/edit/delete, `POST <id>/transition/` |
| Numbering series | `enquiries.` | `enquiries.enquiry`: `ENQ-YYYY-00001`, yearly, gapless |
| State machine | `enquiries.` | `enquiries.enquiry.status` |
| Frontend routes | `/enquiries` | `frontend/enquiries-page.tsx` |

## What it demonstrates, beyond notes

- **Document numbers** minted with `reserve_number()` inside the create's transaction; a unique constraint
  backs the series, and a binned enquiry's number is never reused.
- **A state machine** (`StateMachine` + `transition()`): an illegal move is `409 illegal_transition`, a
  missing reason `400 reason_required`, and every move is written to state history.
  `allowed_transitions` in each response tells the page which buttons to show.
- **Money**: `money_fields()` + `money_property()`; `to_money()` quantises to the currency's scale and an
  unknown currency is a field error. No currency code is hard-coded: the caller sends it.
- Everything comes from `core.sdk` (version 1.2, required at import in `wiring.py`).
