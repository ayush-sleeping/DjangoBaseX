"""The import/export registry (DOMAIN_PRIMITIVES.md § 6, BUILD_ORDER 9.4), on the lookups spec."""

import json

import pytest

from core import dataio, lookups
from core import lookups as lookups_module
from core.models import ActivityLog, LookupValue
from core.registry import LookupSetDef, Registry
from rbac import services as rbac
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

SET = "users.departure_reason"


@pytest.fixture(autouse=True)
def lookup_set(monkeypatch):
    reg = Registry()
    reg.lookups.register(
        LookupSetDef(
            set_key=SET,
            label="Departure",
            admin_can_add=True,
            seed=(("resigned", "Resigned"), ("retired", "Retired")),
        )
    )
    monkeypatch.setattr(lookups_module, "registry", reg)
    lookups.sync_lookups()


@pytest.fixture
def admin():
    role = rbac.create_role(
        actor=None, name="m", slug="m", permission_codes=["settings.lookups.manage"]
    )
    user = UserFactory()
    rbac.assign_role(actor=None, user=user, role=role)
    return user


def rows(admin):
    return dataio.export_rows("core.lookups", admin)


def test_csv_export_has_a_bom_and_neutralises_formula_cells(admin):
    LookupValue.objects.filter(key="retired").update(label='=HYPERLINK("x")')
    data = dataio.export_csv("core.lookups", admin)
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text
    parsed = dataio.parse_csv(data)  # and it round-trips back to the original value
    assert {r["label"] for r in parsed} >= {'=HYPERLINK("x")'}


def test_a_reimport_of_the_same_file_reports_every_row_unchanged_and_is_idempotent(admin):
    data = dataio.export_csv("core.lookups", admin)
    first = dataio.import_rows("core.lookups", dataio.parse_csv(data), actor=admin, dry_run=False)
    assert (first["created"], first["updated"], first["errors"]) == (0, 0, [])
    assert first["unchanged"] == 2
    again = dataio.import_rows("core.lookups", dataio.parse_csv(data), actor=admin, dry_run=False)
    assert again["unchanged"] == 2


def test_import_creates_and_updates_through_the_service_and_audits_it(
    admin, django_capture_on_commit_callbacks
):
    incoming = [
        {
            "set_key": SET,
            "key": "retired",
            "label": "Retired early",
            "sort_order": "5",
            "is_active": "yes",
        },
        {
            "set_key": SET,
            "key": "moved",
            "label": "Moved away",
            "sort_order": "9",
            "is_active": "true",
        },
    ]
    with django_capture_on_commit_callbacks(execute=True):  # the lookup service audits on commit
        report = dataio.import_rows("core.lookups", incoming, actor=admin, dry_run=False)
    assert (report["created"], report["updated"], report["unchanged"]) == (1, 1, 0)
    assert LookupValue.objects.get(key="retired").label == "Retired early"
    assert LookupValue.objects.get(key="moved").sort_order == 9
    actions = set(ActivityLog.objects.values_list("action", flat=True))
    assert {"core.lookup.created", "core.lookup.changed", "core.dataio.imported"} <= actions


def test_a_dry_run_reports_what_would_happen_and_writes_nothing(admin):
    before = LookupValue.objects.count(), ActivityLog.objects.count()
    report = dataio.import_rows(
        "core.lookups", [{"set_key": SET, "key": "moved", "label": "Moved"}], actor=admin
    )
    assert report["created"] == 1 and report["dry_run"] is True
    assert (LookupValue.objects.count(), ActivityLog.objects.count()) == before


def test_bad_rows_are_reported_by_row_number_and_do_not_stop_the_others(admin):
    incoming = [
        {"set_key": SET, "key": "ok-one", "label": "Fine"},
        {"set_key": SET, "key": "Not A Slug", "label": "Bad key"},
        {"set_key": SET, "key": "x", "label": "X", "colour": "red"},
        {"set_key": SET, "label": "No key"},
        {"set_key": SET, "key": "ok-two", "label": "Also fine", "sort_order": "abc"},
    ]
    report = dataio.import_rows("core.lookups", incoming, actor=admin, dry_run=False)
    assert report["created"] == 1  # only ok-one
    assert [e["row"] for e in report["errors"]] == [2, 3, 4, 5]
    assert "unknown columns" in report["errors"][1]["message"]
    assert LookupValue.objects.filter(key="ok-one").exists()
    assert not LookupValue.objects.filter(key="ok-two").exists()


def test_a_system_value_cannot_be_deactivated_by_an_import(admin):
    LookupValue.objects.filter(key="resigned").update(is_system=True)
    report = dataio.import_rows(
        "core.lookups",
        [{"set_key": SET, "key": "resigned", "is_active": "false"}],
        actor=admin,
        dry_run=False,
    )
    assert report["errors"] and LookupValue.objects.get(key="resigned").is_active


def test_the_callers_permission_is_required_both_ways():
    nobody = UserFactory()
    with pytest.raises(dataio.PermissionRefused):
        dataio.export_rows("core.lookups", nobody)
    with pytest.raises(dataio.PermissionRefused):
        dataio.import_rows("core.lookups", [], actor=nobody)
    with pytest.raises(dataio.UnknownSpec):
        dataio.export_rows("nope.nothing", nobody)


def test_json_bundle_round_trips_and_a_foreign_file_is_refused(admin):
    bundle = dataio.export_bundle(["core.lookups"], admin)
    assert bundle["_meta"]["format"] == "djx-bundle" and bundle["_meta"]["counts"] == {
        "core.lookups": 2
    }
    parsed = dataio.parse_bundle(json.dumps(bundle))
    report = dataio.import_rows("core.lookups", parsed["core.lookups"], actor=admin, dry_run=False)
    assert report["unchanged"] == 2
    with pytest.raises(dataio.BadFile):
        dataio.parse_bundle(json.dumps({"core.lookups": []}))
    with pytest.raises(dataio.BadFile):
        dataio.parse_bundle("not json")
