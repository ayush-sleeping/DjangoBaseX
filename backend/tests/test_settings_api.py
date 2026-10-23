"""/api/core/settings/ (CONFIGURATION.md § 9.8): thin views over the one service."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.settings_service import get_setting
from rbac import services
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

KEY = "security.reauth.window_minutes"
LIST = reverse("core:settings")


def client_with(*codes):
    user = UserFactory()
    if codes:
        slug = f"probe-{user.pk}"  # unique per caller: one test builds several clients
        services.assign_role(
            actor=None,
            user=user,
            role=services.create_role(
                actor=None, name=slug, slug=slug, permission_codes=list(codes)
            ),
        )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def detail(key=KEY):
    return reverse("core:setting", kwargs={"key": key})


def test_anonymous_is_401_and_viewer_permission_gates_the_list():
    assert APIClient().get(LIST).status_code == 401
    assert client_with().get(LIST).status_code == 403
    response = client_with("settings.settings.view").get(LIST)
    assert response.status_code == 200
    by_key = {item["key"]: item for item in response.json()}
    item = by_key[KEY]
    assert (item["value"], item["source"], item["default"]) == (15, "default", 15)
    assert item["type"] == "int" and (item["min"], item["max"]) == (1, 1440)
    assert item["updated_by"] is None


def test_the_module_filter_narrows_the_list():
    response = client_with("settings.settings.view").get(LIST, {"module": "nobody"})
    assert response.json() == []


def test_patch_validates_writes_and_reports_the_new_state():
    manager = client_with("settings.settings.manage")
    response = manager.patch(detail(), {"value": 30, "reason": "an audit"}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert (body["value"], body["source"]) == (30, "platform")
    assert body["updated_by"]["email"].startswith("user")
    assert get_setting(KEY) == 30

    refused = manager.patch(detail(), {"value": "soon"}, format="json")
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "invalid_value"
    assert refused.json()["error"]["details"]["rule"] == "must be a whole number"
    assert get_setting(KEY) == 30  # the refused write changed nothing

    out_of_bounds = manager.patch(detail(), {"value": 0}, format="json")
    assert out_of_bounds.status_code == 400 and "at least 1" in str(out_of_bounds.json())


def test_an_unregistered_key_is_404_and_view_alone_cannot_write():
    manager = client_with("settings.settings.manage")
    refused = manager.patch(detail("security.reauth.typo"), {"value": 1}, format="json")
    assert refused.status_code == 404
    viewer = client_with("settings.settings.view")
    assert viewer.patch(detail(), {"value": 30}, format="json").status_code == 403


def test_reset_removes_the_override_and_answers_the_default():
    manager = client_with("settings.settings.manage")
    manager.patch(detail(), {"value": 30}, format="json")
    response = manager.post(reverse("core:setting-reset", kwargs={"key": KEY}), {}, format="json")
    assert response.status_code == 200
    assert (response.json()["value"], response.json()["source"]) == (15, "default")
