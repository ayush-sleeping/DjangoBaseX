"""manage.py seed_demo (BUILD_ORDER 9.6): run twice, each demo row exists once; refused in prod."""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from core.models import ActivityLog
from rbac.models import Role, UserRole

pytestmark = pytest.mark.django_db
User = get_user_model()


def run(*args) -> str:
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def counts():
    return (
        User.objects.filter(email__endswith="@example.test").count(),
        Role.objects.filter(slug="demo-support").count(),
        UserRole.objects.filter(user__email__endswith="@example.test").count(),
    )


def test_seed_demo_twice_creates_each_demo_row_once():
    run()
    assert counts() == (3, 1, 3)
    second = run()
    assert counts() == (3, 1, 3)
    assert "0 created" in second.splitlines()[-1]


def test_demo_data_goes_through_services_so_the_admin_holds_administrator():
    run()
    admin = User.objects.get(email="admin@example.test")
    assert UserRole.objects.filter(user=admin, role__slug="administrator").exists()
    assert (
        ActivityLog.objects.filter(action="users.user.created").count() == 3
    )  # the service wrote the audit rows
    assert admin.has_usable_password()  # a random throwaway, never a fixed value


def test_demo_password_is_random_printed_once_and_not_repeated_on_a_second_run():
    first = run()
    password = first.split("sign in with: ")[1].splitlines()[0]
    assert len(password) >= 20
    assert User.objects.get(email="viewer@example.test").check_password(password)
    assert "sign in with" not in run()  # nothing new was created, so nothing is printed


def test_seed_demo_refuses_when_production_like(settings):
    settings.APP_ENV = "production"
    with pytest.raises(CommandError, match="production-like"):
        run()
    assert counts() == (0, 0, 0)


def test_unknown_app_is_an_error():
    with pytest.raises(CommandError, match="No demo seeder"):
        run("--apps", "nope")
