"""manage.py bootstrap_admin: account one (AUTH_BLUEPRINT § 19.1, A25)."""

import logging
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from rbac.management.commands.bootstrap_admin import PASSWORD_ENV
from rbac.models import Permission, Role, UserRole
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EMAIL = "first@example.com"
STRONG = "Glacier-Orbit-Lantern-73"
User = get_user_model()


@pytest.fixture(autouse=True)
def _no_password_in_env(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)


def answers(monkeypatch, *replies):
    """Feed getpass the given replies in order; fail the test if it asks more often."""
    queue = list(replies)

    def fake_getpass(prompt=""):
        assert queue, f"getpass asked once too often ({prompt!r})"
        return queue.pop(0)

    monkeypatch.setattr("getpass.getpass", fake_getpass)


def run(*args, **options) -> str:
    out = StringIO()
    call_command("bootstrap_admin", *args, stdout=out, stderr=out, **options)
    return out.getvalue()


# --- The happy path -----------------------------------------------------------------------------


def test_creates_one_active_superuser_holding_administrator(monkeypatch):
    answers(monkeypatch, STRONG, STRONG)
    output = run("--email", EMAIL, "--full-name", "First Admin")

    user = User.objects.get()
    assert (user.email, user.full_name) == (EMAIL, "First Admin")
    assert user.is_active and user.is_staff and user.is_superuser
    assert user.check_password(STRONG)
    assert UserRole.objects.filter(user=user, role__slug="administrator").exists()
    assert "Created first@example.com" in output


def test_the_email_is_normalised(monkeypatch):
    answers(monkeypatch, STRONG, STRONG)
    run("--email", "First@Example.COM")
    assert User.objects.get().email == "first@example.com"


def test_the_environment_variable_is_the_non_interactive_path(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV, STRONG)
    answers(monkeypatch)  # any prompt fails the test
    run("--email", EMAIL, "--no-input")
    assert User.objects.get().check_password(STRONG)


def test_an_empty_catalog_is_seeded_first(monkeypatch):
    UserRole.objects.all().delete()
    Role.objects.all().delete()
    Permission.objects.all().delete()
    answers(monkeypatch, STRONG, STRONG)
    run("--email", EMAIL)

    administrator = Role.objects.get(slug="administrator")
    assert administrator.is_system and administrator.is_elevated
    assert Permission.objects.exists()
    granted = set(administrator.permissions.values_list("code", flat=True))
    assert granted == set(Permission.objects.values_list("code", flat=True))
    assert User.objects.get().has_perm("rbac.roles.view")


def test_the_bootstrap_is_audited_with_no_actor(monkeypatch, caplog):
    answers(monkeypatch, STRONG, STRONG)
    with caplog.at_level(logging.INFO, logger="audit"):
        run("--email", EMAIL)
    record = next(r for r in caplog.records if r.audit_verb == "users.user.bootstrapped")
    assert record.audit_actor is None
    assert record.audit_target == User.objects.get().public_id


# --- Refusals -----------------------------------------------------------------------------------


def test_refuses_with_exit_code_1_once_any_user_exists(monkeypatch):
    UserFactory(is_active=False)  # any row at all, active or not
    answers(monkeypatch)  # refused before any prompt
    with pytest.raises(CommandError, match="users already exist") as exc:
        run("--email", EMAIL)
    assert exc.value.returncode == 1
    assert User.objects.count() == 1


def test_a_second_run_creates_nothing(monkeypatch):
    answers(monkeypatch, STRONG, STRONG)
    run("--email", EMAIL)
    with pytest.raises(CommandError, match="users already exist"):
        run("--email", "second@example.com")
    assert list(User.objects.values_list("email", flat=True)) == [EMAIL]


def test_mismatched_passwords_are_refused(monkeypatch):
    answers(monkeypatch, STRONG, STRONG + "x")
    with pytest.raises(CommandError, match="do not match"):
        run("--email", EMAIL)
    assert not User.objects.exists()


def test_an_empty_password_is_refused_without_a_second_prompt(monkeypatch):
    answers(monkeypatch, "")
    with pytest.raises(CommandError, match="empty password"):
        run("--email", EMAIL)
    assert not User.objects.exists()


# Common, numeric, like the email, too short. None is a word that occurs in a validator message.
@pytest.mark.parametrize("weak", ["qwertyuiop", "12345678", "first@example.com", "Zx9!"])
def test_a_weak_password_is_refused(monkeypatch, weak):
    answers(monkeypatch, weak, weak)
    with pytest.raises(CommandError, match="Password refused") as exc:
        run("--email", EMAIL)
    assert weak not in str(exc.value)
    assert not User.objects.exists()


def test_a_weak_password_from_the_environment_is_refused_too(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV, "password")
    with pytest.raises(CommandError, match="Password refused"):
        run("--email", EMAIL, "--no-input")
    assert not User.objects.exists()


def test_no_input_without_the_environment_variable_is_refused(monkeypatch):
    answers(monkeypatch)
    with pytest.raises(CommandError, match=f"{PASSWORD_ENV} must be set"):
        run("--email", EMAIL, "--no-input")


def test_an_invalid_email_is_refused_before_any_prompt(monkeypatch):
    answers(monkeypatch)
    with pytest.raises(CommandError, match="not a valid email"):
        run("--email", "not-an-address")


def test_the_email_is_required():
    with pytest.raises(CommandError, match="--email"):
        run()


def test_a_failure_after_creating_the_user_rolls_everything_back(monkeypatch):
    def explode(**kwargs):
        raise RuntimeError("assign failed")

    monkeypatch.setattr("rbac.services.assign_role", explode)
    answers(monkeypatch, STRONG, STRONG)
    with pytest.raises(RuntimeError):
        run("--email", EMAIL)
    assert not User.objects.exists()


# --- The password never leaks -------------------------------------------------------------------


def test_the_password_appears_in_no_output(monkeypatch, capsys, caplog):
    monkeypatch.setenv(PASSWORD_ENV, STRONG)
    with caplog.at_level(logging.DEBUG):
        output = run("--email", EMAIL, "--no-input")
    captured = capsys.readouterr()
    for text in (output, captured.out, captured.err, caplog.text):
        assert STRONG not in text
    for record in caplog.records:
        assert STRONG not in repr(record.__dict__)
