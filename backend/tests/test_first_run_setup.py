"""The first-run wizard (BUILD_ORDER 9.5; OPERATIONS.md § 3): open only while setup is pending."""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from rbac import setup

STATUS = "/api/rbac/setup/status/"
COMPLETE = "/api/rbac/setup/complete/"
GOOD = {"email": "first@example.test", "password": "Correct-Horse-Battery-7", "full_name": "First"}

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_throttles():
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


def token() -> str:
    return setup.issue_token()


def test_a_fresh_install_reports_setup_required(client):
    assert client.get(STATUS).json() == {"setup_required": True}


def test_completing_with_the_token_creates_the_administrator_and_seals_setup(client):
    response = client.post(COMPLETE, {**GOOD, "token": token()}, format="json")
    assert response.status_code == 204
    user = get_user_model().objects.get(email=GOOD["email"])
    assert user.is_superuser and user.is_active
    assert client.get(STATUS).json() == {"setup_required": False}
    assert setup.get_setting(setup.TOKEN_KEY) == ""  # the token died with the setup


def test_the_endpoint_is_closed_after_setup(client):
    first = token()
    assert client.post(COMPLETE, {**GOOD, "token": first}, format="json").status_code == 204
    again = client.post(
        COMPLETE, {**GOOD, "email": "b@example.test", "token": first}, format="json"
    )
    assert again.status_code == 404  # not 403: no oracle for "set up by the wizard"
    assert get_user_model().objects.count() == 1


def test_a_wrong_or_missing_token_creates_nothing(client):
    token()
    wrong = client.post(COMPLETE, {**GOOD, "token": "nope"}, format="json")
    assert wrong.status_code == 403
    assert get_user_model().objects.count() == 0


def test_without_an_issued_token_nothing_can_complete(client):
    assert client.post(COMPLETE, {**GOOD, "token": "anything"}, format="json").status_code == 403
    assert get_user_model().objects.count() == 0


def test_a_weak_password_is_refused_and_the_token_survives(client):
    t = token()
    weak = client.post(COMPLETE, {**GOOD, "password": "123", "token": t}, format="json")
    assert weak.status_code == 400
    assert get_user_model().objects.count() == 0
    assert client.post(COMPLETE, {**GOOD, "token": t}, format="json").status_code == 204


def test_the_token_is_stored_hashed_only():
    t = token()
    stored = setup.get_setting(setup.TOKEN_KEY)
    assert stored and t not in stored


def test_bootstrap_admin_and_the_wizard_seal_each_other(client):
    t = token()
    setup.create_first_admin("cli@example.test", GOOD["password"])  # what bootstrap_admin calls
    assert client.post(COMPLETE, {**GOOD, "token": t}, format="json").status_code == 404
    with pytest.raises(CommandError, match="already complete"):
        call_command("setup_token")


def test_issuing_a_token_after_setup_is_refused():
    setup.create_first_admin("cli@example.test", GOOD["password"])
    with pytest.raises(setup.SetupSealed):
        setup.issue_token()


def test_the_setup_token_command_prints_a_working_token_once(capsys, client):
    call_command("setup_token")
    printed = capsys.readouterr().out.split(": ")[-1].strip()
    assert client.post(COMPLETE, {**GOOD, "token": printed}, format="json").status_code == 204
