"""The scanner behind test_permission_codes.py, on synthetic source (AUTH_BLUEPRINT § 9.3).

If the scanner silently misses a shape, the real test passes vacuously for every code written that
way. These pin each shape it must see, and each place it must not look.
"""

import textwrap

import pytest

from tests.architecture.permission_refs import find_permission_refs


def write(root, relative, source):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))
    return path


# --- (a) has_perm -------------------------------------------------------------------------------


def test_has_perm_as_a_method_and_as_a_bare_name(tmp_path):
    write(
        tmp_path,
        "billing/services.py",
        """\
        def f(request, user, backend):
            request.user.has_perm("billing.invoices.view")
            backend.has_perm(user, "not.this.one")  # the FIRST argument is the code
            has_perm("billing.invoices.send")
            user_has_perm("billing.invoices.export", obj=None)
        """,
    )
    refs = find_permission_refs(tmp_path)
    assert refs == {
        "billing.invoices.view": ["billing/services.py:2"],
        "billing.invoices.send": ["billing/services.py:4"],
        "billing.invoices.export": ["billing/services.py:5"],
    }


def test_has_perms_reads_every_code_in_its_list(tmp_path):
    write(tmp_path, "billing/views.py", 'user.has_perms(["billing.a.view", "billing.b.view"])\n')
    assert set(find_permission_refs(tmp_path)) == {"billing.a.view", "billing.b.view"}


def test_has_perm_with_a_variable_is_not_a_reference(tmp_path):
    write(tmp_path, "billing/views.py", "code = 'x'\nuser.has_perm(code)\nuser.has_perm()\n")
    assert find_permission_refs(tmp_path) == {}


# --- (b) HasPermission --------------------------------------------------------------------------


def test_every_string_argument_of_has_permission(tmp_path):
    write(
        tmp_path,
        "billing/views.py",
        """\
        from core import permissions

        class InvoiceView:
            permission_classes = [
                HasPermission("billing.invoices.view"),
                permissions.HasPermission("billing.invoices.send", "billing.invoices.export"),
                AnyHasPermission(code="billing.reports.view"),
            ]
        """,
    )
    assert set(find_permission_refs(tmp_path)) == {
        "billing.invoices.view",
        "billing.invoices.send",
        "billing.invoices.export",
        "billing.reports.view",
    }


# --- (c) required_permissions -------------------------------------------------------------------


def test_required_permissions_dicts_lists_and_nesting(tmp_path):
    write(
        tmp_path,
        "billing/views.py",
        """\
        class InvoiceViewSet:
            required_permissions = {
                "list": "billing.invoices.view",
                "create": ["billing.invoices.create", "billing.invoices.view"],
                "destroy": ("billing.invoices.delete",),
            }

        class ReportView:
            required_permissions: list[str] = ["billing.reports.view"]

        view.required_permissions = {"get": "billing.reports.export"}

        @action(detail=True, required_permissions={"post": "billing.invoices.send"})
        def send(self, request): ...
        """,
    )
    refs = find_permission_refs(tmp_path)
    assert set(refs) == {
        "billing.invoices.view",
        "billing.invoices.create",
        "billing.invoices.delete",
        "billing.reports.view",
        "billing.reports.export",
        "billing.invoices.send",
    }
    # Dict keys like "list" are not codes. One code referenced twice lists both lines.
    assert refs["billing.invoices.view"] == ["billing/views.py:3", "billing/views.py:4"]


def test_other_assignments_are_not_references(tmp_path):
    write(
        tmp_path,
        "billing/constants.py",
        """\
        CODES = ["billing.invoices.view"]
        permissions = {"list": "billing.invoices.send"}
        log("billing.invoices.export")
        """,
    )
    assert find_permission_refs(tmp_path) == {}


# --- Only code-shaped strings -------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "billing.invoices",
        "Billing.invoices.view",
        "billing.invoices.view.extra",
        "a sentence about billing.invoices.view",
        "",
        "users:login",
    ],
)
def test_strings_that_are_not_codes_are_ignored(tmp_path, value):
    write(
        tmp_path,
        "billing/views.py",
        f"user.has_perm({value!r})\nrequired_permissions = [{value!r}]\n",
    )
    assert find_permission_refs(tmp_path) == {}


# --- Where it does not look ---------------------------------------------------------------------

REFERENCE = 'user.has_perm("billing.invoices.view")\n'


@pytest.mark.parametrize(
    "relative",
    [
        "tests/test_billing.py",
        "tests/helpers.py",
        "billing/tests/test_views.py",
        "billing/tests/factories.py",
        "billing/migrations/0002_seed.py",
        ".venv/lib/python3.12/site-packages/thing.py",
        "billing/__pycache__/views.py",
        ".ruff_cache/x.py",
        "billing/tests.py",
        "billing/test_views.py",
        "conftest.py",
    ],
)
def test_tests_migrations_and_tooling_are_not_scanned(tmp_path, relative):
    write(tmp_path, relative, REFERENCE)
    assert find_permission_refs(tmp_path) == {}


def test_a_file_named_like_an_excluded_dir_is_still_scanned(tmp_path):
    write(tmp_path, "billing/migrations_helper.py", REFERENCE)
    write(tmp_path, "billing/testing.py", REFERENCE)
    assert find_permission_refs(tmp_path) == {
        "billing.invoices.view": ["billing/migrations_helper.py:1", "billing/testing.py:1"]
    }


def test_a_file_that_does_not_parse_fails_loudly(tmp_path):
    write(tmp_path, "billing/broken.py", "def (:\n")
    with pytest.raises(SyntaxError):
        find_permission_refs(tmp_path)


def test_the_default_root_is_the_backend_and_finds_this_repos_code():
    # Not an assertion about the catalog (test_permission_codes.py owns that): only that the
    # default root is the backend and not, say, tests/architecture.
    from tests.architecture.permission_refs import BACKEND

    assert (BACKEND / "manage.py").is_file()
