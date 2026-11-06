"""The open-findings queue (DOMAIN_PRIMITIVES.md § 8)."""

import pytest
from django.db import IntegrityError, transaction

from core import findings
from core.models import Finding
from core.registry import FindingKind, Registry, RegistryError

pytestmark = pytest.mark.django_db


@pytest.fixture
def kinds():
    reg = Registry()
    reg.finding_kinds.register(
        FindingKind(
            kind="billing.drift",
            label="Invoice differs from the provider",
            severity="warning",
            owner_module="billing",
            resolutions=("restored", "dismissed"),
        )
    )
    return reg.finding_kinds


def detect(kinds, object_id="7", **details):
    return findings.raise_or_touch(
        "billing.drift",
        object_type="billing.invoice",
        object_id=object_id,
        details=details,
        kinds=kinds,
    )


def test_two_detections_are_one_open_row(kinds):
    first = detect(kinds, total=10)
    second = detect(kinds, total=12)
    assert first.pk == second.pk
    assert (second.occurrences, second.details, second.severity) == (2, {"total": 12}, "warning")
    assert second.title == "Invoice differs from the provider"
    assert second.last_seen_at >= second.first_seen_at


def test_each_object_has_its_own_row(kinds):
    detect(kinds, "7")
    detect(kinds, "8")
    assert Finding.objects.open().count() == 2


def test_resolve_then_detect_opens_a_second_row(kinds):
    first = detect(kinds)
    assert findings.resolve(first, "restored", note="re-synced by hand", kinds=kinds)
    assert (first.resolution, first.resolution_note) == ("restored", "re-synced by hand")
    second = detect(kinds)
    assert second.pk != first.pk and second.occurrences == 1
    assert Finding.objects.count() == 2
    assert not findings.resolve(first, "dismissed", kinds=kinds)  # already history


def test_a_resolution_must_be_one_the_kind_allows(kinds):
    with pytest.raises(ValueError, match="restored"):
        findings.resolve(detect(kinds), "deleted_it", kinds=kinds)


def test_unregistered_kind_is_refused(kinds):
    with pytest.raises(findings.UnknownFindingKind):
        findings.raise_or_touch("billing.nobody", object_type="x", object_id="1", kinds=kinds)


def test_clear_on_recovery(kinds):
    detect(kinds)
    assert findings.clear(
        "billing.drift", object_type="billing.invoice", object_id="7", kinds=kinds
    )
    row = Finding.objects.get()
    assert (row.resolution, row.resolved_by) == ("auto_cleared", None)
    assert (
        findings.clear("billing.drift", object_type="billing.invoice", object_id="7", kinds=kinds)
        == 0
    )


def test_a_model_instance_is_its_own_subject(kinds, django_user_model):
    user = django_user_model.objects.create(email="drift@example.com")
    row = findings.raise_or_touch("billing.drift", user, kinds=kinds)
    assert (row.object_type, row.object_id) == (user._meta.label_lower, str(user.pk))


def test_a_finding_is_about_something(kinds):
    with pytest.raises(ValueError):
        findings.raise_or_touch("billing.drift", kinds=kinds)


def test_the_database_holds_one_open_row_per_problem(kinds):
    row = detect(kinds)
    duplicate = {
        f: getattr(row, f)
        for f in (
            "kind",
            "object_type",
            "object_id",
            "title",
            "severity",
            "first_seen_at",
            "last_seen_at",
        )
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        Finding.objects.create(**duplicate)


def test_a_kind_is_validated_at_registration():
    reg = Registry()
    good = dict(
        kind="billing.drift",
        label="x",
        severity="warning",
        owner_module="billing",
        resolutions=("dismissed",),
    )
    for bad in ({"kind": "Drift"}, {"severity": "loud"}, {"resolutions": ()}, {"label": " "}):
        with pytest.raises(RegistryError):
            reg.finding_kinds.register(FindingKind(**(good | bad)))
