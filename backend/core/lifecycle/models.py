"""
The lifecycle models (DATA_LIFECYCLE.md § 5, 7, 8): StateTransition, and the abstract mixins
SoftDeleteModel and ProvenanceModel that a user-facing model inherits.
"""

import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from core.querysets import VisibleToQuerySet

SOURCE_REF_PATTERN = r"^[A-Za-z0-9._:/#-]{1,191}$"


class AppendOnlyError(Exception):
    pass


class StateTransition(models.Model):
    """
    One change of a registered state field (DATA_LIFECYCLE.md § 5): (object, field, from, to, who,
    when, why). Written only by core.lifecycle.transitions.change_state(), in the same transaction
    as the change. A snapshot, not a foreign key: history survives the object and its actor.
    Append-only: an existing row is never rewritten or deleted through the model.
    """

    object_type = models.CharField(max_length=100)  # "users.user"
    object_id = models.CharField(max_length=64)  # the public id when it has one
    field = models.CharField(max_length=64)
    from_state = models.CharField(max_length=64, blank=True, default="")
    to_state = models.CharField(max_length=64, blank=True, default="")
    actor_id = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    actor_label = models.CharField(max_length=255, blank=True, default="")  # "system" when no actor
    source = models.CharField(max_length=16, blank=True, default="")
    reason = models.CharField(max_length=255, blank=True, default="")
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "core_state_transition"
        ordering = ["-id"]
        indexes = [
            models.Index(
                fields=["object_type", "object_id", "occurred_at"], name="core_statetr_object"
            ),
            models.Index(fields=["field", "to_state", "occurred_at"], name="core_statetr_field"),
        ]

    def __str__(self):
        return (
            f"{self.object_type}#{self.object_id} {self.field}: {self.from_state}→{self.to_state}"
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("core_state_transition is append-only: a saved row cannot change")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("core_state_transition is append-only: delete() is refused")


# --- Soft delete (§ 7) --------------------------------------------------------------------------


class RestoreConflict(Exception):
    """A live row holds a value this binned row's unique constraint needs (409 restore_conflict)."""


class SoftDeleteQuerySet(models.QuerySet):
    """
    delete() here SOFT-deletes (a bulk UPDATE), so `Model.objects.filter(...).delete()` can never
    hard-delete by accident; the destructive call is the explicitly named hard_delete().
    """

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):
        count = self.alive().update(deleted_at=timezone.now())
        return count, {self.model._meta.label: count}

    def hard_delete(self):
        return super().delete()

    delete.alters_data = True
    hard_delete.alters_data = True


class SoftDeleteManager(models.Manager):
    """The default manager: deleted rows are hidden, so forgetting is the safe direction."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


def soft_delete_managers(queryset_class=SoftDeleteQuerySet):
    """`objects, all_objects = soft_delete_managers(MyQuerySet)` — the pair a model declares. The
    queryset class must subclass SoftDeleteQuerySet (and, to be scoped, VisibleToQuerySet)."""
    alive = SoftDeleteManager.from_queryset(queryset_class)()
    everything = models.Manager.from_queryset(queryset_class)()
    return alive, everything


class SoftDeleteModel(models.Model):
    """
    deleted_at / deleted_by / deletion_batch, hide-by-default, restore.

    Cascade is per relation, never implicit: SOFT_DELETE_CASCADE names the reverse relations whose
    live rows are binned with this one, in ONE bulk UPDATE sharing a deletion_batch (so memory is
    flat however many children). Restore brings back exactly that batch. It is one level deep: a
    child that has children of its own declares its own relations and is deleted through its own
    soft_delete(). Uniqueness uses live_unique() (a partial index), never unique=True (dbx.E050).
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    deletion_batch = models.UUIDField(null=True, blank=True)

    SOFT_DELETE_CASCADE: tuple[str, ...] = ()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def _children(self, relation: str):
        rel = self._meta.get_field(relation)
        child = rel.related_model
        if not issubclass(child, SoftDeleteModel):
            raise TypeError(
                f"{child.__name__} must be a SoftDeleteModel to cascade from {relation}"
            )
        return child, rel.field.name

    def soft_delete(self, *, actor=None) -> uuid.UUID:
        """Bin this row and its declared children; returns the batch id."""
        batch, now = uuid.uuid4(), timezone.now()
        with transaction.atomic():
            for relation in self.SOFT_DELETE_CASCADE:
                child, fk = self._children(relation)
                child.all_objects.filter(**{fk: self, "deleted_at__isnull": True}).update(
                    deleted_at=now, deleted_by=actor, deletion_batch=batch
                )
            self.deleted_at, self.deleted_by, self.deletion_batch = now, actor, batch
            self.save(update_fields=["deleted_at", "deleted_by", "deletion_batch"])
        return batch

    def delete(self, using=None, keep_parents=False):
        """Soft: the Model.delete() every caller (admin, shell) reaches bins the row."""
        self.soft_delete()

    def hard_delete(self):
        return super().delete()

    def restore(self):
        """Un-bin the row and its batch. A live row holding a unique value → RestoreConflict."""
        batch = self.deletion_batch
        try:
            with transaction.atomic():
                self.deleted_at, self.deleted_by, self.deletion_batch = None, None, None
                self.save(update_fields=["deleted_at", "deleted_by", "deletion_batch"])
                if batch is not None:
                    for relation in self.SOFT_DELETE_CASCADE:
                        child, _ = self._children(relation)
                        child.all_objects.filter(deletion_batch=batch).update(
                            deleted_at=None, deleted_by=None, deletion_batch=None
                        )
        except IntegrityError as exc:
            raise RestoreConflict("A live row already holds a value this one needs.") from exc

    delete.alters_data = True
    hard_delete.alters_data = True


def live_unique(*fields: str, name: str) -> models.UniqueConstraint:
    """Uniqueness among live rows only: a binned row's value can be reused (§ 7.2)."""
    return models.UniqueConstraint(
        fields=list(fields), condition=models.Q(deleted_at__isnull=True), name=name
    )


# --- Provenance (§ 8) ---------------------------------------------------------------------------


class ProvenanceModel(models.Model):
    """
    How a row came to exist, in two halves with different trust. NULL means unknown and is never
    backfilled or defaulted: adding this mixin leaves existing rows NULL.
      created_via — the API consumer, from the authenticated principal, never the payload;
      origin      — web · api · import · job · system, from the write's provenance at insert;
      source_ref  — the caller's pointer to its own record: a pointer, never evidence.
    Stamp it with core.lifecycle.provenance.stamp(); serializers declare all three read-only.
    """

    created_via = models.ForeignKey(
        "core.ApiConsumer", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    origin = models.CharField(max_length=16, null=True, blank=True)  # noqa: DJ001 — NULL = unknown
    source_ref = models.CharField(  # noqa: DJ001 — NULL = unknown
        max_length=191,
        null=True,
        blank=True,
        db_index=True,  # plain index: a unique one would silently become an idempotency key
        validators=[RegexValidator(SOURCE_REF_PATTERN, "Letters, digits and . _ : / # - only.")],
    )

    class Meta:
        abstract = True


__all__ = [
    "ProvenanceModel",
    "RestoreConflict",
    "SoftDeleteModel",
    "SoftDeleteQuerySet",
    "StateTransition",
    "VisibleToQuerySet",
    "live_unique",
    "soft_delete_managers",
]
