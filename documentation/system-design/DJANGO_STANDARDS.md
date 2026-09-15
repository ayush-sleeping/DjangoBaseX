# Django / DRF Standards

**Conventions you must follow when writing backend code.** This is a *how to write it* doc, not a
*what exists* doc — for the latter see [`../core/ARCHITECTURE.md`](../core/ARCHITECTURE.md).

The governing rule is in `AGENTS.md` § 3: **match the surrounding code, and don't introduce a second
way of doing something.** Where this file and the existing code disagree, raise it rather than
silently picking one.

---

## 1. Running anything

**Always through `uv run`** ([ADR-0003](../adr/0003-uv-manages-the-backend-toolchain.md)). There is
no "activate the venv" step.

```bash
cd backend
uv run python manage.py runserver
uv run python manage.py makemigrations
uv run python manage.py migrate
uv run ruff check .
uv run ruff format .
```

---

## 2. Creating a new app

```bash
cd backend && uv run python manage.py startapp <name>
```

Then, in the same change:

1. Add `"<name>"` to `INSTALLED_APPS` in `config/settings.py` (under `# Local`)
2. Add `"<name>"` to `known-first-party` in `backend/pyproject.toml` — **easy to forget**, and the
   symptom is misleading: Ruff starts failing on files you did not touch, because the new app's
   imports sort as third-party
3. Create `<name>/urls.py` and include it from `config/urls.py` under `/api/`
4. Delete the `tests.py` stub if you are adding a `tests/` package instead

---

## 3. Layers

A request flows **URL → view → service → model**. Each layer has exactly one job.

| Layer | Does | Never does |
|-------|------|-----------|
| `urls.py` | Maps a path to a view | Anything else |
| `views.py` | Parse input, check permission, call a service, return a Response | Business logic, multi-step orchestration, direct ORM beyond a trivial lookup |
| `serializers.py` | Shape and validate | Queries, side effects, business rules, sending email |
| `services.py` | Business logic, orchestration, transactions | Touch `request` or return a `Response` |
| `models.py` | Fields, constraints, `Meta`, `__str__`, simple properties | Business workflows |
| `managers.py` / queryset methods | Named, reusable queries | — |

**Why the service layer** — the alternative is logic in views, which cannot be reused by a management
command, a Celery task or the admin, and cannot be tested without building a request.

### A view should read like this

```python
class EnquiryViewSet(viewsets.ModelViewSet):
    serializer_class = EnquirySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Enquiry.objects.for_user(self.request.user)   # a queryset method, not a filter chain

    def perform_create(self, serializer):
        services.create_enquiry(actor=self.request.user, **serializer.validated_data)
```

If a view grows past a screen, the excess belongs in a service.

---

## 4. Models

- **Explicit `on_delete`** on every `ForeignKey`. Ruff's `DJ` rules enforce it; think about the answer
  rather than reaching for `CASCADE` by reflex
- **`__str__` on every model.** Also a `DJ` rule, and it is what makes the admin usable
- **Constraints in the database**, via `Meta.constraints` — not only in a serializer. A serializer is
  bypassed by the admin, a shell, a management command and a data migration
- `DEFAULT_AUTO_FIELD` is `BigAutoField`, set project-wide. Do not override per model
- Prefer `TextChoices`/`IntegerChoices` over bare tuples
- **Timestamps:** `created_at = models.DateTimeField(auto_now_add=True)`,
  `updated_at = models.DateTimeField(auto_now=True)`. Consider a shared abstract base in `core/` once
  a second model needs them — not before
- **Never** `null=True` on a `CharField`/`TextField`. Use `blank=True` and an empty string; two
  representations of "no value" is a bug generator

---

## 5. Queries

- **`select_related` / `prefetch_related` when you cross a relation in a loop or a serializer.** The
  N+1 is the default performance bug in any Django project, and DRF's nested serializers make it
  easy to write without noticing
- Named queryset methods over repeated filter chains:
  ```python
  class EnquiryQuerySet(models.QuerySet):
      def active(self):
          return self.filter(is_archived=False)
  ```
- **Never** `.all()` into Python to count or check existence — use `.count()` and `.exists()`
- Wrap multi-write operations in `transaction.atomic()`, in the **service**, not the view

---

## 6. API conventions

- **URLs:** `/api/<resource>/`, plural, lowercase, kebab-case, **trailing slash** (Django's default —
  be consistent or `APPEND_SLASH` will surprise you on POST)
- **Routers** (`DefaultRouter`) for standard CRUD; explicit paths for anything else
- **Pagination is on by default** (`PageNumberPagination`, `PAGE_SIZE: 20`). Do not disable it for a
  list that can grow
- **Permissions are `IsAuthenticated` by default and that default fails closed.** Opening a view to
  the public is an explicit, per-view `permission_classes = [AllowAny]` — and should be rare enough
  to be worth a comment saying why
- **Never trust `request.data` for ownership.** A `user` or `owner` field comes from `request.user`,
  never from the payload. This is the most common authorization bug in DRF code
- **Document non-obvious endpoints** with `@extend_schema` — drf-spectacular generates `/api/schema/`,
  and a wrong schema is worse than none

---

## 7. Errors

- Raise DRF exceptions (`ValidationError`, `PermissionDenied`, `NotFound`) — do not hand-build error
  `Response` objects. Consistent shape matters to the frontend
- Validate in the serializer (`validate_<field>`, `validate`), not in the view
- **Never leak internals** in an error message: no stack traces, no SQL, no file paths. `DEBUG=False`
  handles the unhandled case; your own messages are your responsibility

---

## 8. Settings and secrets

- Every environment-dependent value comes from `.env` via `django-environ`. **Nothing hard-coded**
- Add the key to `backend/.env.example` **with a placeholder** in the same change
- **Never print, log, commit or paste a `.env` value.** Key names only (`AGENTS.md` § 1, rule 6)
- `DEBUG=True` is for local development only

---

## 9. Before you say it's done

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run   # after ANY model change
```

There is **no test suite yet** — so these four are the whole safety net. Report their real output,
including failures (`AGENTS.md` § 1, rule 9).
