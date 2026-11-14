"""
Data lifecycle (BUILD_ORDER 9.3): state-transition history, soft delete with partial unique
constraints and per-relation cascade, the recycle bin's registry-key rule, provenance stamping.
The notes plugin proves the same end to end (examples/plugins/notes/.../tests).
"""

import uuid

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, models, transaction
from django.test import Client

from core.lifecycle import provenance
from core.lifecycle.models import (
    AppendOnlyError,
    RestoreConflict,
    SoftDeleteModel,
    SoftDeleteQuerySet,
    StateTransition,
    live_unique,
    soft_delete_managers,
)
from core.lifecycle.recyclebin import register_recyclable
from core.lifecycle.transitions import UnregisteredStateField, change_state, history
from core.registry import Recyclable, Registry, RegistryError
from rbac import services as rbac
from tests.factories import DEFAULT_PASSWORD, UserFactory
from users.cookies import cookie_names
from users.services import users as users_service

# --- State-transition history (§ 5) -------------------------------------------------------------


@pytest.mark.django_db
def test_deactivate_and_activate_each_record_one_transition_with_the_actor():
    admin, user = UserFactory(), UserFactory()
    users_service.deactivate(actor=admin, user=user, reason="left the company")
    users_service.activate(actor=admin, user=user)

    rows = list(history(user, "is_active"))
    assert [(r.from_state, r.to_state) for r in rows] == [("True", "False"), ("False", "True")]
    assert rows[0].reason == "left the company"
    assert rows[0].actor_label == admin.email and rows[0].actor_id == str(admin.public_id)
    assert rows[0].object_type == "users.user" and rows[0].object_id == str(user.public_id)


@pytest.mark.django_db
def test_a_system_write_is_recorded_as_system_and_a_no_op_records_nothing():
    user = UserFactory()
    assert change_state(user, "is_active", False) is True
    row = history(user).get()
    assert row.actor_id is None and row.actor_label == "system"
    assert change_state(user, "is_active", False) is False
    assert StateTransition.objects.count() == 1


@pytest.mark.django_db
def test_a_field_nobody_registered_is_refused_and_history_is_append_only():
    user = UserFactory()
    with pytest.raises(UnregisteredStateField):
        change_state(user, "full_name", "x")
    change_state(user, "is_active", False)
    row = StateTransition.objects.get()
    row.reason = "rewritten"
    with pytest.raises(AppendOnlyError):
        row.save()
    with pytest.raises(AppendOnlyError):
        row.delete()


# --- Soft delete (§ 7): test-only tables, created and dropped inside the test -------------------


class _ParentQS(SoftDeleteQuerySet):
    pass


@pytest.fixture(scope="module")
def _soft_tables(django_db_setup, django_db_blocker):
    """Parent/Child tables for this module, created and dropped OUTSIDE any test transaction.

    Never `transactional_db`: its teardown flush TRUNCATEs the audit log, which the append-only
    trigger refuses on PostgreSQL (TRAPS.md). The tables are real DDL, built once; each test runs
    in the normal rolled-back transaction, so they are empty at the next test and at the drop.
    The models are unregistered from the app registry afterwards.
    """

    class Parent(SoftDeleteModel):
        sku = models.CharField(max_length=20)
        objects, all_objects = soft_delete_managers(_ParentQS)
        SOFT_DELETE_CASCADE = ("lines",)

        class Meta:
            app_label = "core"
            db_table = "t_lifecycle_parent"
            constraints = [live_unique("sku", name="t_parent_sku_live")]

    class Child(SoftDeleteModel):
        parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name="lines")
        objects, all_objects = soft_delete_managers(SoftDeleteQuerySet)

        class Meta:
            app_label = "core"
            db_table = "t_lifecycle_child"

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.create_model(Parent)
            editor.create_model(Child)
        try:
            yield Parent, Child
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(Child)
                editor.delete_model(Parent)
            for name in ("parent", "child"):
                apps.all_models["core"].pop(name, None)
            apps.clear_cache()


@pytest.fixture
def soft_models(_soft_tables, db):
    return _soft_tables


def test_the_default_manager_hides_deleted_rows_and_all_objects_shows_them(soft_models):
    Parent, _ = soft_models
    keep, gone = Parent.objects.create(sku="a"), Parent.objects.create(sku="b")
    gone.delete()  # Model.delete() bins, it does not hard-delete
    assert list(Parent.objects.all()) == [keep]
    assert set(Parent.all_objects.all()) == {keep, gone}
    assert list(Parent.all_objects.deleted()) == [gone]


def test_queryset_delete_bins_and_never_hard_deletes(soft_models):
    Parent, _ = soft_models
    Parent.objects.create(sku="a")
    Parent.objects.create(sku="b")
    count, _ = Parent.objects.all().delete()
    assert count == 2 and Parent.objects.count() == 0 and Parent.all_objects.count() == 2
    Parent.all_objects.all().delete()  # already binned: stays binned, no second stamp
    assert Parent.all_objects.count() == 2
    Parent.all_objects.all().hard_delete()  # the explicit, separately named call
    assert Parent.all_objects.count() == 0


def test_a_deleted_rows_unique_value_can_be_reused_and_restore_then_conflicts(soft_models):
    Parent, _ = soft_models
    first = Parent.objects.create(sku="X-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        Parent.objects.create(sku="X-1")  # live rows are still unique
    first.soft_delete()
    second = Parent.objects.create(sku="X-1")  # a binned row's value is free again
    with pytest.raises(RestoreConflict):
        first.restore()
    first.refresh_from_db()
    assert first.is_deleted  # the failed restore left it binned
    second.soft_delete()
    first.restore()
    assert list(Parent.objects.all()) == [first]


def test_cascade_is_one_batch_per_relation_and_restore_brings_back_exactly_it(soft_models):
    Parent, Child = soft_models
    parent = Parent.objects.create(sku="p")
    earlier = Child.objects.create(parent=parent)
    earlier.soft_delete()  # deleted on its own, before the parent: must stay deleted
    c1, c2 = Child.objects.create(parent=parent), Child.objects.create(parent=parent)

    batch = parent.soft_delete()
    assert Child.objects.count() == 0
    assert set(Child.all_objects.filter(deletion_batch=batch)) == {c1, c2}

    parent.restore()
    assert set(Child.objects.all()) == {c1, c2}
    assert Child.all_objects.get(pk=earlier.pk).is_deleted


def test_a_soft_deletable_model_with_a_unique_column_fails_the_boot_check(soft_models):
    from core.checks import check_soft_deletable_models_have_no_unique_columns as check

    Parent, _ = soft_models
    assert check(None) == []

    class Bad(SoftDeleteModel):
        code = models.CharField(max_length=5, unique=True)

        class Meta:
            app_label = "core"
            db_table = "t_lifecycle_bad"

    try:
        assert [e.id for e in check(None)] == ["dbx.E050"]
    finally:
        apps.all_models["core"].pop("bad", None)
        apps.clear_cache()


# --- The recycle bin refuses what it cannot safely scope ---------------------------------------


def test_registering_a_model_that_is_not_soft_deletable_is_refused():
    with pytest.raises(RegistryError, match="not a SoftDeleteModel"):
        register_recyclable(
            Registry(),
            Recyclable(
                key="users.user",
                model="users.User",
                label="Users",
                title_field="email",
                delete_permission="users.users.deactivate",
            ),
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "type_key", ["nothing.here", "users.User", "django.contrib.auth.models.User"]
)
def test_an_unknown_or_class_name_type_is_a_404(type_key):
    user = UserFactory()
    role = rbac.create_role(
        actor=None, name="bin", slug="bin", permission_codes=["core.recycle_bin.manage"]
    )
    rbac.assign_role(actor=None, user=user, role=role)
    client = Client()
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )
    assert client.get("/api/recycle-bin/", {"type": type_key}).status_code == 404
    csrf = client.cookies.get(cookie_names().csrf).value
    bogus = f"/api/recycle-bin/{type_key.replace('.', '-')}/{uuid.uuid4()}/restore/"
    assert client.post(bogus, HTTP_X_CSRF_TOKEN=csrf).status_code == 404
    assert "types" in client.get("/api/recycle-bin/").json()


@pytest.mark.django_db
def test_the_bin_needs_its_one_permission():
    user = UserFactory()
    client = Client()
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )
    assert client.get("/api/recycle-bin/").status_code == 403


# --- Provenance (§ 8) ----------------------------------------------------------------------------


def test_stamp_takes_the_consumer_from_the_principal_and_validates_source_ref():
    class Consumer:
        pass

    class Machine:
        is_machine = True
        consumer = Consumer()

    machine = provenance.stamp(actor=Machine(), source_ref="crm:42")
    assert machine["origin"] == "api" and machine["created_via"] is Machine.consumer
    assert machine["source_ref"] == "crm:42"

    human = provenance.stamp(actor=object())
    assert human["created_via"] is None and human["origin"] in {"web", "system"}
    assert human["source_ref"] is None  # NULL = unknown, never defaulted

    with pytest.raises(ValueError):
        provenance.stamp(source_ref="bad\nref")
