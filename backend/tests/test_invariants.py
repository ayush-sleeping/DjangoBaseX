"""The invariant pattern (DOMAIN_PRIMITIVES.md § 1.4): the database holds the rule when clean()
is bypassed, and its refusal maps to one typed error."""

import pytest
from django.db import IntegrityError

from core.invariants import (
    InvariantViolation,
    constraint_name,
    invariant_scope,
    map_integrity_error,
)
from core.models import Setting

pytestmark = pytest.mark.django_db

RULES = {"core_setting_scope_type_known": "A setting's scope must be platform, tenant or user."}


@pytest.mark.parametrize(
    "message, name",
    [
        (
            'new row for relation "core_setting" violates check constraint '
            '"core_setting_scope_type_known"',
            "core_setting_scope_type_known",
        ),
        ("CHECK constraint failed: core_setting_scope_type_known", "core_setting_scope_type_known"),
        (
            'duplicate key value violates unique constraint "core_setting_one_platform_row"',
            "core_setting_one_platform_row",
        ),
        ("UNIQUE constraint failed: core_setting.key", "core_setting.key"),
        ("something else entirely", None),
    ],
)
def test_constraint_name_is_parsed_from_both_backends(message, name):
    assert constraint_name(IntegrityError(message)) == name


def test_an_unlisted_constraint_is_not_mapped():
    exc = IntegrityError('violates check constraint "other_rule"')
    assert map_integrity_error(exc, RULES) is None


def test_a_queryset_update_that_bypasses_clean_is_still_refused_by_the_database():
    row = Setting.objects.create(key="probe.x.y", scope_type="platform", value={"v": 1})
    with pytest.raises(InvariantViolation) as caught:
        with invariant_scope(RULES):
            Setting.objects.filter(pk=row.pk).update(scope_type="bogus")  # no clean() runs here
    assert caught.value.constraint == "core_setting_scope_type_known"
    assert str(caught.value) == RULES["core_setting_scope_type_known"]
    assert caught.value.code == "invariant_violated"
    row.refresh_from_db()
    assert row.scope_type == "platform"  # the savepoint rolled the write back


def test_other_integrity_errors_propagate_unchanged():
    Setting.objects.create(key="probe.x.y", scope_type="platform", value={"v": 1})
    with pytest.raises(IntegrityError):
        with invariant_scope(RULES):
            Setting.objects.create(key="probe.x.y", scope_type="platform", value={"v": 2})
