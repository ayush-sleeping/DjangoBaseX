"""
GET /api/me/bootstrap/ (FRONTEND_PLATFORM § 7, BUILD_ORDER 8.2).

The parity test is the point: `permissions` must be exactly what has_perm() answers, code by code
over the whole catalogue, for every kind of principal. A UI that computes permissions differently
from the API hides actions people may take, or shows ones they may not.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from core import bootstrap
from core.registry import registry
from rbac import services as rbac
from tests.factories import DEFAULT_PASSWORD, UserFactory
from users import bootstrap as users_bootstrap

pytestmark = pytest.mark.django_db

URL = "/api/me/bootstrap/"
CATALOGUE = sorted(registry.permissions.codes())


def signed_in(user) -> Client:
    client = Client()
    response = client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 204
    return client


def with_codes(*codes):
    user = UserFactory()
    role = rbac.create_role(
        actor=None, name=f"r-{user.pk}", slug=f"r-{user.pk}", permission_codes=codes
    )
    rbac.assign_role(actor=None, user=user, role=role)
    return user


def test_anonymous_callers_are_refused():
    assert Client().get(URL).status_code == 401


def test_the_shell_gets_every_essential_section_in_one_call():
    user = with_codes("users.users.view")
    response = signed_in(user).get(URL)

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    body = response.json()
    assert body["user"]["email"] == user.email
    assert "permissions" not in body["user"]  # one place per fact
    assert body["permissions"] == ["users.users.view"]
    assert body["session"]["expires_at"] and body["session"]["idle_expires_at"]
    assert body["server_time"]
    assert {s["key"] for s in body["nav"]} >= {"home", "people"}
    assert body["degraded"] == []


def test_a_superusers_permissions_are_the_full_catalogue():
    user = UserFactory(is_superuser=True)
    assert signed_in(user).get(URL).json()["permissions"] == CATALOGUE


@pytest.mark.parametrize("principal", ["plain", "granted", "superuser"])
def test_permissions_equal_what_has_perm_answers_for_every_code(principal):
    user = {
        "plain": lambda: UserFactory(),
        "granted": lambda: with_codes("users.users.view", "rbac.roles.view"),
        "superuser": lambda: UserFactory(is_superuser=True),
    }[principal]()
    listed = set(signed_in(user).get(URL).json()["permissions"])
    fresh = get_user_model().objects.get(pk=user.pk)  # no cached permission sets

    assert {code for code in CATALOGUE if fresh.has_perm(code)} == listed


def test_me_and_bootstrap_compute_permissions_the_same_way():
    client = signed_in(with_codes("users.users.view"))
    assert (
        client.get("/api/auth/me/").json()["permissions"] == client.get(URL).json()["permissions"]
    )


def boom(request):
    raise RuntimeError("contributor broke")


def test_a_raising_decorative_contributor_is_degraded_not_fatal(monkeypatch):
    monkeypatch.setattr(
        users_bootstrap,
        "CONTRIBUTORS",
        (*users_bootstrap.CONTRIBUTORS, bootstrap.Contributor("badges", boom)),
    )
    response = signed_in(UserFactory()).get(URL)

    assert response.status_code == 200
    assert response.json()["degraded"] == ["badges"]
    assert "badges" not in response.json()


def test_a_raising_essential_contributor_fails_the_response(monkeypatch):
    monkeypatch.setattr(
        users_bootstrap,
        "CONTRIBUTORS",
        (*users_bootstrap.CONTRIBUTORS, bootstrap.Contributor("scope", boom, essential=True)),
    )
    client = signed_in(UserFactory())
    client.raise_request_exception = False

    assert client.get(URL).status_code == 500


def test_a_key_contributed_twice_is_refused():
    twice = (bootstrap.Contributor("x", lambda r: 1), bootstrap.Contributor("x", lambda r: 2))
    with pytest.raises(ValueError, match="contributed twice"):
        bootstrap.assemble(object(), twice)
