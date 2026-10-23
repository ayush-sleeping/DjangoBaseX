"""Admin-editable lookups (CONFIGURATION.md § 14): stable keys, grandfathering, seed humility."""

from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework import serializers
from rest_framework.test import APIClient

from core import lookups as lookups_module
from core.lookups import LookupField, LookupRefused, set_lookup_value, sync_lookups
from core.models import LookupValue
from core.registry import LookupSetDef, Registry, RegistryError
from rbac import services
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

SET = "users.departure_reason"


def set_def(**overrides):
    base = dict(
        set_key=SET,
        label="Departure reason",
        seed=(("resigned", "Resigned"), ("retired", "Retired"), ("other", "Other", True)),
    )
    base.update(overrides)
    return LookupSetDef(**base)


@pytest.fixture(autouse=True)
def registered(monkeypatch):
    from core.api import lookups as lookups_api

    reg = Registry()
    reg.lookups.register(set_def())
    for module in (lookups_module, lookups_api):
        monkeypatch.setattr(module, "registry", reg)
    sync_lookups()
    return reg


# --- Declaration and seeding ----------------------------------------------------------------------


def test_the_declaration_is_validated():
    reg = Registry()
    with pytest.raises(RegistryError, match="not <module>.<name>"):
        reg.lookups.register(set_def(set_key="departure"))
    with pytest.raises(RegistryError, match="seeds 'x' twice"):
        reg.lookups.register(set_def(seed=(("x", "X"), ("x", "Y"))))
    with pytest.raises(RegistryError, match="not a slug"):
        reg.lookups.register(set_def(seed=(("Not A Slug", "X"),)))


def test_sync_inserts_missing_keys_only_and_never_touches_the_admins_edits():
    row = LookupValue.objects.get(set_key=SET, key="resigned")
    assert (row.label, row.is_active, row.is_system) == ("Resigned", True, False)
    assert LookupValue.objects.get(set_key=SET, key="other").is_system is True

    set_lookup_value(SET, "resigned", label="Resigned (voluntary)")
    set_lookup_value(SET, "retired", is_active=False)
    LookupValue.objects.get(set_key=SET, key="other").delete()  # a hand-deleted seed returns
    assert sync_lookups() == [f"{SET}:other"]
    assert LookupValue.objects.get(set_key=SET, key="resigned").label == "Resigned (voluntary)"
    assert LookupValue.objects.get(set_key=SET, key="retired").is_active is False  # not reactivated


# --- The writer -----------------------------------------------------------------------------------


def test_an_admin_adds_a_value_with_no_deploy_and_the_key_is_stable(
    audit_rows, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        row = set_lookup_value(SET, "contract-ended", create=True, label="Contract ended")
    assert row.key == "contract-ended" and row.is_active
    assert [r.action for r in audit_rows() if r.action.startswith("core.lookup")] == [
        "core.lookup.created"
    ]
    with pytest.raises(LookupRefused, match="already exists"):
        set_lookup_value(SET, "contract-ended", create=True, label="Again")
    with pytest.raises(LookupRefused, match="does not accept"):
        lookups_module.registry.lookups._defs[SET] = set_def(admin_can_add=False)
        set_lookup_value(SET, "one-more", create=True, label="One more")


def test_label_changes_are_audited_old_to_new(audit_rows, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        set_lookup_value(SET, "resigned", label="Resigned (voluntary)")
    (event,) = audit_rows("core.lookup.changed")
    assert event.meta["old"]["label"] == "Resigned"
    assert event.meta["new"]["label"] == "Resigned (voluntary)"


def test_a_system_value_cannot_be_deactivated():
    with pytest.raises(LookupRefused, match="system value"):
        set_lookup_value(SET, "other", is_active=False)
    set_lookup_value(SET, "other", label="Other (please specify)")  # relabel is fine


def test_meta_is_validated_by_the_sets_schema():
    def schema(meta):
        if "colour" not in meta:
            raise ValueError("needs a colour")

    lookups_module.registry.lookups._defs[SET] = set_def(meta_schema=schema)
    with pytest.raises(LookupRefused, match="needs a colour"):
        set_lookup_value(SET, "resigned", meta={})
    set_lookup_value(SET, "resigned", meta={"colour": "grey"})


# --- Grandfathering (§ 14, the done-when) ---------------------------------------------------------


class RecordSerializer(serializers.Serializer):
    reason = LookupField(set_key=SET)


def test_a_deactivated_value_is_refused_on_create_but_renders_on_old_rows():
    retired = LookupValue.objects.get(set_key=SET, key="retired")
    set_lookup_value(SET, "retired", is_active=False)
    retired.refresh_from_db()

    fresh = RecordSerializer(data={"reason": "retired"})
    assert not fresh.is_valid() and "reason" in fresh.errors  # refused for NEW data

    holder = SimpleNamespace(reason=retired)
    unchanged = RecordSerializer(holder, data={"reason": "retired"})
    assert unchanged.is_valid(), unchanged.errors  # grandfathered where already held
    assert unchanged.validated_data["reason"] == retired

    moved = RecordSerializer(SimpleNamespace(reason=None), data={"reason": "retired"})
    assert not moved.is_valid()  # and refused as a CHANGE to it

    # The old row still renders its label: deactivation never blanks history.
    assert retired.label == "Retired"


def test_membership_comes_from_the_table_not_a_literal():
    serializer = RecordSerializer(data={"reason": "contract-ended"})
    assert not serializer.is_valid()
    set_lookup_value(SET, "contract-ended", create=True, label="Contract ended")
    assert RecordSerializer(data={"reason": "contract-ended"}).is_valid()  # no deploy in between


# --- The API --------------------------------------------------------------------------------------


def client_with(*codes):
    user = UserFactory()
    if codes:
        slug = f"lk-{user.pk}"
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


def test_any_signed_in_user_reads_and_only_manage_writes():
    assert APIClient().get(reverse("core:lookups")).status_code == 401
    listing = client_with().get(reverse("core:lookups"), {"set": SET})
    assert listing.status_code == 200
    assert {v["key"] for v in listing.json()} == {"resigned", "retired", "other"}
    assert client_with().get(reverse("core:lookups"), {"set": "users.typo"}).status_code == 404

    add = reverse("core:lookup-add", kwargs={"set_key": SET})
    body = {"key": "contract-ended", "label": "Contract ended"}
    assert client_with().post(add, body, format="json").status_code == 403
    manager = client_with("settings.lookups.manage")
    assert manager.post(add, body, format="json").status_code == 201

    value = reverse("core:lookup-value", kwargs={"set_key": SET, "key": "contract-ended"})
    edited = manager.patch(value, {"label": "Contract ended (fixed term)"}, format="json")
    assert edited.status_code == 200 and edited.json()["label"] == "Contract ended (fixed term)"
    renamed = manager.patch(value, {"key": "renamed"}, format="json")
    assert renamed.status_code == 200 and renamed.json()["key"] == "contract-ended"  # key ignored
