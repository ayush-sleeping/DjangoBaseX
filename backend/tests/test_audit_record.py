"""The one writer, provenance, capture, commands and the read side (DATA_LIFECYCLE.md § 4)."""

import sys
import uuid

import pytest
from django.db import connection, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from core import audit
from core.audit import AuditedCommand, AuditedModelMixin, batch, log_activity, record
from core.models import ActivityLog, AppendOnlyError
from rbac import services
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


# --- record() --------------------------------------------------------------------------------


def test_record_writes_a_row_with_actor_snapshot_target_and_scrubbed_meta():
    actor, target = UserFactory(), UserFactory()
    row = record(
        "users.user.updated",
        target,
        actor=actor,
        meta={"note": "ok", "password": "hunter2-hunter2", "nested": {"api_key": "k" * 40}},
    )
    assert row.channel == "rbac" and row.description == "User updated"  # registered label
    assert (row.actor_id, row.actor_label) == (str(actor.public_id), actor.email)
    assert (row.target_type, row.target_id) == ("users.user", str(target.public_id))
    assert row.target_repr == target.email
    assert (
        row.meta["note"] == "ok" and "hunter2" not in str(row.meta) and "kkkk" not in str(row.meta)
    )


def test_an_unregistered_action_still_logs_with_a_derived_label():
    row = record("crm.deal.won")
    assert row is not None and row.description == "Crm deal won" and row.channel == "crm"


def test_log_activity_keeps_its_call_shape_and_now_writes_rows(audit_rows):
    user = UserFactory()
    log_activity("users.user.created", user, user, via="test")  # verb, actor, target, **meta
    (row,) = audit_rows("users.user.created")
    assert row.meta == {"via": "test"} and row.actor_id == str(user.public_id)


def test_record_never_raises_and_counts_the_failure(monkeypatch):
    before = audit.write_failures

    def boom(self, *a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(ActivityLog, "save", boom)
    assert record("users.user.updated") is None  # swallowed, not raised
    assert audit.write_failures == before + 1


def test_a_failed_insert_does_not_break_the_outer_transaction(monkeypatch):
    # The row's savepoint isolates a database error: the OUTER transaction stays usable (§ 4.2).
    real_save = ActivityLog.save

    def poisoned(self, *a, **k):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM table_that_does_not_exist")

    monkeypatch.setattr(ActivityLog, "save", poisoned)
    with transaction.atomic():
        assert record("users.user.updated") is None
        assert UserFactory().pk  # the outer transaction still works after the failed audit write
    monkeypatch.setattr(ActivityLog, "save", real_save)


def test_a_rolled_back_change_leaves_no_row():
    before = ActivityLog.objects.count()  # migrate's own audit rows are already there
    with pytest.raises(ZeroDivisionError):
        with transaction.atomic():
            record("users.user.updated")
            raise ZeroDivisionError
    assert ActivityLog.objects.count() == before  # transactional: no row claims it happened


def test_independent_degrades_to_transactional_without_the_audit_alias(caplog):
    row = record("auth.token_reuse_detected", independent=True)
    assert row is not None  # SQLite development: no DATABASES["audit"], so it still writes


def test_rows_in_a_batch_share_its_id():
    with batch() as batch_id:
        a, b = record("users.user.updated"), record("users.user.created")
    assert a.batch_id == b.batch_id == batch_id and isinstance(batch_id, uuid.UUID)
    assert record("users.user.updated").batch_id is None


# --- Provenance (inferred; the ActorContext binder is 7.x) -----------------------------------


def test_a_command_write_is_attributed_to_the_command_the_os_user_and_the_host(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["manage.py", "set_setting", "k", "v", "--password", "hunter2"]
    )
    row = record("core.setting.changed")
    assert row.source == "command" and row.origin_os_user and row.origin_host
    assert row.origin_command.startswith("manage.py set_setting k v")
    assert "hunter2" not in row.origin_command  # a --password argument must not land in the log


def test_a_web_write_carries_the_request_id(monkeypatch):
    from core.observability import request_id

    token = request_id.REQUEST_ID.set("req-123")
    try:
        row = record("users.user.updated")
    finally:
        request_id.REQUEST_ID.reset(token)
    assert (row.source, row.via, row.request_id) == ("web", "api", "req-123")


# --- Immutability, layers 1-3 (layer 4 is Postgres-only, below) ------------------------------


def test_instance_queryset_and_bulk_writes_are_refused():
    row = record("users.user.updated")
    row.description = "tampered"
    with pytest.raises(AppendOnlyError):
        row.save()
    with pytest.raises(AppendOnlyError):
        row.delete()
    with pytest.raises(AppendOnlyError):
        ActivityLog.objects.all().update(description="x")
    with pytest.raises(AppendOnlyError):
        ActivityLog.objects.all().delete()
    with pytest.raises(AppendOnlyError):
        ActivityLog.objects.bulk_update([row], ["description"])
    assert ActivityLog.objects.get(pk=row.pk).description == "User updated"


@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="the trigger is PostgreSQL-only (§ 4.7)"
)
def test_postgres_trigger_refuses_raw_sql_and_allows_only_the_retention_purge():
    from django.db import IntegrityError

    row = record("users.user.updated")
    for sql in (
        "UPDATE core_activity_log SET description = 'x'",
        "DELETE FROM core_activity_log",
        "TRUNCATE core_activity_log",
    ):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)
    assert ActivityLog.objects.filter(pk=row.pk).exists()
    with transaction.atomic(), connection.cursor() as cursor:  # the retention engine's flag
        cursor.execute("SET LOCAL core.retention_purge = 'on'")
        cursor.execute("DELETE FROM core_activity_log")
    assert ActivityLog.objects.count() == 0


# --- Capture (opt-in) and commands -----------------------------------------------------------


@pytest.fixture
def Audited(db):
    """
    A captured model for these tests: a PROXY of LookupValue built in an isolated app registry, so
    it uses a real table, needs no DDL (SQLite cannot run a schema editor inside a test
    transaction), and never reaches the global registry or makemigrations.
    """
    from django.test.utils import isolate_apps

    from core.models import LookupValue

    with isolate_apps():  # empty registry: "core" would re-run CoreConfig.ready()

        class AuditedLookup(AuditedModelMixin, LookupValue):
            class AuditMeta:
                preference_fields = ("sort_order",)
                title_field = "label"

            class Meta:
                app_label = "core"
                proxy = True

        yield AuditedLookup


def make(Audited, **fields):
    return Audited.objects.create(set_key="users.probe", key="k1", label="L1", **fields)


def test_capture_records_create_then_only_the_real_diff(Audited, audit_rows):
    editor = UserFactory()
    make(Audited)
    (created,) = audit_rows("core.auditedlookup.created")
    assert created.event == "created" and created.description == "L1 — created"

    row = Audited.objects.get(key="k1")  # from_db takes the snapshot: no extra query
    row.sort_order, row.updated_by = 99, None  # a preference field, and nothing else
    row.save()
    assert audit_rows("core.auditedlookup.updated") == []  # nothing real changed ⇒ NO row

    row.label, row.updated_by = "L2", editor
    row.meta = {"colour": "grey", "api_key": "k" * 40}
    row.save()
    (updated,) = audit_rows("core.auditedlookup.updated")
    assert set(updated.changes) == {"label", "updated_by", "meta.colour", "meta.api_key"}
    assert updated.changes["label"] == {"old": "L1", "new": "L2"}
    assert updated.changes["updated_by"]["new_label"] == editor.email  # the FK's str() then
    assert updated.changes["meta.api_key"] == {"old": "*****", "new": "*****", "secret": True}
    assert "kkkk" not in str(updated.changes)


def test_a_status_only_save_reads_as_status_changed(Audited, audit_rows):
    row = make(Audited)
    row = Audited.objects.get(pk=row.pk)
    row.is_active = False  # is_active is a default state field
    row.save()
    (event,) = audit_rows("core.auditedlookup.updated")
    assert event.event == "status_changed" and event.description == "L1 — status changed"


def test_a_delete_is_captured_and_a_deferred_field_costs_no_query(
    Audited, audit_rows, django_assert_num_queries
):
    row = make(Audited)
    with django_assert_num_queries(1):  # the .only() load itself; the snapshot adds none
        deferred = Audited.objects.only("label").get(pk=row.pk)
    deferred.delete()
    (gone,) = audit_rows("core.auditedlookup.deleted")
    assert gone.event == "deleted" and gone.description == "L1 — deleted"


class Quiet(AuditedCommand):
    def handle(self, *a, **k):
        pass


class Busy(AuditedCommand):
    def handle(self, *a, **k):
        record("users.user.created")
        record("users.user.updated", event="updated")


def test_a_command_run_writes_one_summary_only_if_something_happened(audit_rows):
    from django.core.management import call_command

    call_command(Quiet())
    assert audit_rows("core.command.ran") == []  # nothing happened → nothing recorded
    call_command(Busy())
    (summary,) = audit_rows("core.command.ran")
    assert summary.event == "run_summary" and summary.meta["counts"]
    members = [r for r in audit_rows() if r.action != "core.command.ran"]
    assert {r.batch_id for r in members} == {summary.batch_id}  # one run reads as one thing


# --- The read side ---------------------------------------------------------------------------


def client_with(*codes):
    user = UserFactory()
    slug = f"aud-{user.pk}"
    if codes:
        services.assign_role(
            actor=None,
            user=user,
            role=services.create_role(
                actor=None, name=slug, slug=slug, permission_codes=list(codes)
            ),
        )
    client = APIClient()
    client.force_authenticate(user=type(user).objects.get(pk=user.pk))  # no stale permission cache
    return client, user


def test_the_log_is_readable_with_the_permission_and_has_no_write_route():
    record("users.user.created")
    anyone, _ = client_with()
    assert anyone.get(reverse("core:activity")).status_code == 403
    reader, _ = client_with("core.audit.view")
    response = reader.get(reverse("core:activity"))
    assert response.status_code == 200
    body = response.json()
    rows = body["results"] if isinstance(body, dict) else body
    created = next(r for r in rows if r["action"] == "users.user.created")
    assert (created["tone"], created["label"]) == ("success", "User created")
    for verb in ("post", "put", "patch", "delete"):
        assert getattr(reader, verb)(reverse("core:activity")).status_code == 405
    # id is the sort key, newest first
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids, reverse=True)


def test_the_export_streams_oldest_first_escapes_formulas_and_is_itself_audited(audit_rows):
    record("users.user.created", description='=HYPERLINK("http://evil")')
    record("users.user.updated")
    exporter, actor = client_with("core.audit.export")
    response = exporter.get(reverse("core:activity-export"))
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    assert "audit-" in response["Content-Disposition"] and response["Content-Disposition"].endswith(
        'Z.csv"'
    )
    body = b"".join(response.streaming_content).decode()
    lines = body.splitlines()
    assert lines[0].startswith("id,created_at,channel,action")
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body  # CSV-injection escaped
    ids = [int(line.split(",", 1)[0]) for line in lines[1:] if line[0].isdigit()]
    assert ids == sorted(ids)  # oldest first
    (event,) = audit_rows("core.audit.exported")
    assert event.actor_id == str(actor.public_id)  # the export is itself an event
