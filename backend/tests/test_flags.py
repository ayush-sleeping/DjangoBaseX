"""Feature flags: the six resolution rules, the writer, the gate, /me and the admin API (§ 11)."""

import logging
from datetime import date, timedelta

import pytest
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from core import flags as flags_module
from core.api.views import BaseAPIView
from core.flags import UnknownFlag, flag_enabled, flags_for, requires_flag, set_flag
from core.models import FeatureFlag
from core.registry import FlagDef, Registry, RegistryError
from rbac import services
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

KEY = "users.probe_screen"


def flag_def(key=KEY, **overrides):
    base = dict(
        key=key,
        owner="core-team",
        expires_on=date.today() + timedelta(days=30),
        description="A probe flag.",
    )
    base.update(overrides)
    return FlagDef(**base)


@pytest.fixture(autouse=True)
def registered(monkeypatch):
    """A registry with one declared flag, patched in everywhere core.flags looks."""
    from core.api import flags as flags_api

    reg = Registry()
    reg.flags.register(flag_def())
    monkeypatch.setattr(flags_module, "registry", reg)
    monkeypatch.setattr(flags_api, "registry", reg)
    return reg


def user_with_role(slug="probers"):
    user = UserFactory()
    services.assign_role(
        actor=None,
        user=user,
        role=services.create_role(actor=None, name=slug, slug=slug, permission_codes=[]),
    )
    return user


# --- The six resolution rules (§ 11) --------------------------------------------------------------


def test_rule_1_an_unregistered_key_is_off_even_with_an_enabled_row():
    FeatureFlag.objects.create(key="users.deleted_flag", enabled=True)
    assert flag_enabled("users.deleted_flag", user=UserFactory()) is False


def test_rule_2_no_row_yet_is_off_for_everyone():
    assert flag_enabled(KEY) is False
    assert flag_enabled(KEY, user=UserFactory()) is False


def test_rule_3_the_kill_switch_beats_every_target():
    user = UserFactory()
    FeatureFlag.objects.create(key=KEY, enabled=False, user_ids=[str(user.public_id)])
    assert flag_enabled(KEY, user=user) is False  # "disabled except for targets" cannot exist


def test_rule_4_enabled_with_no_targeting_is_on_for_everyone_signed_in_or_not():
    FeatureFlag.objects.create(key=KEY, enabled=True)
    assert flag_enabled(KEY) is True
    assert flag_enabled(KEY, user=UserFactory()) is True


def test_rule_5_targeting_narrows_and_anonymous_matches_nothing():
    targeted, other = UserFactory(), UserFactory()
    role_holder = user_with_role()
    FeatureFlag.objects.create(
        key=KEY, enabled=True, user_ids=[str(targeted.public_id)], role_slugs=["probers"]
    )
    assert flag_enabled(KEY, user=targeted) is True
    assert flag_enabled(KEY, user=role_holder) is True
    assert flag_enabled(KEY, user=other) is False
    assert flag_enabled(KEY) is False  # anonymous


def test_rule_6_empty_targeting_is_no_targeting():
    # The column is NOT NULL (default []), so "NULL vs []" cannot diverge at the database; the
    # resolver still treats a missing or None value as [] for rows written by hand.
    FeatureFlag.objects.create(key=KEY, enabled=True, user_ids=[], role_slugs=[], tenant_ids=[])
    assert flag_enabled(KEY, user=UserFactory()) is True
    set_flag(KEY, user_ids=["someone-else"])
    assert flag_enabled(KEY, user=UserFactory()) is False
    set_flag(KEY, user_ids=[])  # clearing targets widens back to everyone
    assert flag_enabled(KEY, user=UserFactory()) is True


def test_registration_requires_owner_and_expiry():
    reg = Registry()
    with pytest.raises(RegistryError, match="expiry"):
        reg.flags.register(flag_def(expires_on=None))
    with pytest.raises(RegistryError, match="empty owner"):
        reg.flags.register(flag_def(owner=" "))
    with pytest.raises(RegistryError, match="not <module>.<name>"):
        reg.flags.register(flag_def(key="users.probe.deep"))


# --- The writer, cache and audit ------------------------------------------------------------------


def test_the_writer_refuses_unknown_keys_and_junk_targeting():
    with pytest.raises(UnknownFlag):
        set_flag("users.typo", enabled=True)
    with pytest.raises(ValueError, match="list of ids"):
        set_flag(KEY, user_ids="not-a-list")
    with pytest.raises(ValueError, match="true or false"):
        set_flag(KEY, enabled=1)
    assert FeatureFlag.objects.count() == 0  # nothing written on refusal


def test_a_toggle_lands_at_once_and_is_audited(caplog, django_capture_on_commit_callbacks):
    assert flag_enabled(KEY) is False  # cached absence
    with caplog.at_level(logging.INFO, logger="audit"):
        with django_capture_on_commit_callbacks(execute=True):
            set_flag(KEY, enabled=True, actor=None, reason="launch")
    assert flag_enabled(KEY) is True  # the generation bump abandons the cached absence
    events = [r for r in caplog.records if r.message == "core.flag.changed"]
    assert len(events) == 1
    assert events[0].audit_meta["old"] is None and events[0].audit_meta["new"]["enabled"] is True

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="audit"):
        with django_capture_on_commit_callbacks(execute=True):
            set_flag(KEY, enabled=True)  # no change: no audit
    assert not [r for r in caplog.records if r.message == "core.flag.changed"]


# --- The route gate (§ 11: unreleased is undiscoverable) ------------------------------------------


def test_a_flagged_route_is_404_when_off_and_normal_when_on():
    class Probe(BaseAPIView):
        required_permissions = []
        permission_classes = [*BaseAPIView.permission_classes, requires_flag(KEY)]

        def get(self, request):
            return Response({"ok": True})

    user = UserFactory()
    request = APIRequestFactory().get("/probe/")
    force_authenticate(request, user=user)
    assert Probe.as_view()(request).status_code == 404  # undiscoverable, not 403
    set_flag(KEY, enabled=True)
    assert Probe.as_view()(request).status_code == 200
    with pytest.raises(UnknownFlag):
        requires_flag("users.typo")  # a typo fails at declaration, not silently at runtime


# --- /me and the admin API ------------------------------------------------------------------------


def client_as(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_me_lists_only_flags_on_for_this_caller():
    user = UserFactory()
    assert flags_for(user) == []
    assert client_as(user).get(reverse("users:me")).json()["flags"] == []
    set_flag(KEY, enabled=True, user_ids=[str(user.public_id)])
    assert client_as(user).get(reverse("users:me")).json()["flags"] == [KEY]
    other = UserFactory()
    assert client_as(other).get(reverse("users:me")).json()["flags"] == []  # not the catalogue


def test_the_admin_api_is_gated_and_audits_through_the_one_writer():
    viewer, manager = UserFactory(), UserFactory()
    services.assign_role(
        actor=None,
        user=viewer,
        role=services.create_role(
            actor=None, name="fv", slug="fv", permission_codes=["settings.flags.view"]
        ),
    )
    services.assign_role(
        actor=None,
        user=manager,
        role=services.create_role(
            actor=None, name="fm", slug="fm", permission_codes=["settings.flags.manage"]
        ),
    )
    listing = client_as(viewer).get(reverse("core:flags"))
    assert listing.status_code == 200
    (item,) = listing.json()
    assert (item["key"], item["enabled"], item["owner"]) == (KEY, False, "core-team")
    assert item["days_remaining"] == 30

    detail = reverse("core:flag", kwargs={"key": KEY})
    assert client_as(viewer).patch(detail, {"enabled": True}, format="json").status_code == 403
    flipped = client_as(manager).patch(detail, {"enabled": True}, format="json")
    assert flipped.status_code == 200 and flipped.json()["enabled"] is True
    missing = client_as(manager).patch(
        reverse("core:flag", kwargs={"key": "users.typo"}), {"enabled": True}, format="json"
    )
    assert missing.status_code == 404
