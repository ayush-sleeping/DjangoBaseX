---
name: new-django-app
description: Create a new Django app (a new domain) in backend/ the way this repository expects. Use before running startapp or adding a new top-level backend package.
argument-hint: "<app_name>"
---

# New Django app

The conventions are in `documentation/system-design/DJANGO_STANDARDS.md` § 2 and `AGENTS.md` § 3, under
"Where new code goes". This is the procedure.

1. **Decide whether it belongs here at all.** Ask: *would a product copied from this boilerplate want it?* If it
   serves only one product, it does not go in this repository (`AGENTS.md` § 3; `documentation/VISION.md`).
   If it is genuinely shared, check whether it belongs in `backend/core/` rather than in a new app.
2. **Check the plan.** `documentation/planning/BUILD_ORDER.md` and
   `documentation/planning/CORE_ARCHITECTURE_PLAN.md` may already name this app, its files and its seams. Follow
   them rather than inventing a layout.
3. **Create it with `DJANGO_STANDARDS.md` § 2**, using the exact commands given there and run with `uv run` from
   `backend/`.
4. **Wire it up.** Register it in `INSTALLED_APPS` and include its urls from `config/urls.py`. Both are
   protected or collision files (`AGENTS.md` § 1), so the guard will ask the user to confirm.
5. **Keep the layers** (`AGENTS.md` § 3): thin `views.py`, business logic in `services.py`, querysets on the
   model, serializers that only shape and validate.
6. **Before the first model, read `.claude/rules/migrations.md`'s pointers.** `DATA_MODEL.md` § 1 has five
   decisions to make first.
7. **Add the app name to Ruff's `known-first-party`** in `backend/pyproject.toml` (see `TECH_DEBT.md` DB-14).
   That is a protected file, so ask.
8. Finish with `/verify` and `/changelog`.
