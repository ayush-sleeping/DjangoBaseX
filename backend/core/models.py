"""
Setting overrides (CONFIGURATION.md § 9.2). A row exists only where an admin changed a value at a
scope; absence means the code default. What a setting IS (its type, label, default) lives in code,
in registry.settings, never here. Read and write through core.settings_service only.
"""

from django.conf import settings
from django.db import models


class SettingQuerySet(models.QuerySet):
    def for_key(self, key: str):
        return self.filter(key=key)

    def at(self, scope_type: str, scope_id: str | None):
        if scope_type == Setting.Scope.PLATFORM:
            return self.filter(scope_type=scope_type, scope_id__isnull=True)
        return self.filter(scope_type=scope_type, scope_id=scope_id)


class Setting(models.Model):
    class Scope(models.TextChoices):
        PLATFORM = "platform"
        TENANT = "tenant"
        USER = "user"

    # Not a foreign key to anything: a row for a key no longer registered is kept and reported, so
    # a rollback that briefly un-registers a key does not lose the admin's value (§ 9.2).
    key = models.CharField(max_length=128, db_index=True)
    scope_type = models.CharField(max_length=16, choices=Scope.choices)
    # The tenant's or user's PUBLIC id; NULL exactly when the scope is the platform. NULL, not "":
    # the per-scope uniqueness and the scope check both read "no scope" as NULL (§ 9.2).
    scope_id = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    # Always {"v": value}: a bare false, 0, "" or null cannot be told from "no row" (§ 9.3).
    value = models.JSONField()
    # Platform rows only: lower scopes are ignored while it is set (§ 9.5).
    is_locked = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = SettingQuerySet.as_manager()

    class Meta:
        db_table = "core_setting"
        ordering = ["key", "scope_type", "scope_id"]
        constraints = [
            # Two partial constraints, because a plain unique (key, scope_type, scope_id) treats
            # the platform row's NULL scope_id as distinct and allows two. Same on SQLite and
            # PostgreSQL (ADR-0005).
            models.UniqueConstraint(
                fields=["key"],
                condition=models.Q(scope_type="platform"),
                name="core_setting_one_platform_row",
            ),
            models.UniqueConstraint(
                fields=["key", "scope_type", "scope_id"],
                condition=~models.Q(scope_type="platform"),
                name="core_setting_one_row_per_scope",
            ),
            models.CheckConstraint(
                condition=models.Q(scope_type__in=["platform", "tenant", "user"]),
                name="core_setting_scope_type_known",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type="platform", scope_id__isnull=True)
                    | (~models.Q(scope_type="platform") & models.Q(scope_id__isnull=False))
                ),
                name="core_setting_scope_id_iff_not_platform",
            ),
            models.CheckConstraint(
                condition=models.Q(is_locked=False) | models.Q(scope_type="platform"),
                name="core_setting_only_platform_locks",
            ),
        ]

    def __str__(self):
        where = self.scope_type if self.scope_id is None else f"{self.scope_type}:{self.scope_id}"
        return f"{self.key} @ {where}"


class FeatureFlag(models.Model):
    """
    A flag's state and targeting (CONFIGURATION.md § 11). The declaration — owner, expiry,
    description — lives in code (registry.flags); a row exists once an admin writes one, and a key
    with no row is off. Read and write through core.flags only.
    """

    key = models.CharField(max_length=128, unique=True)
    # The kill switch: False is off for everyone, targets included (§ 11 rule 3).
    enabled = models.BooleanField(default=False)
    # Targeting narrows who a live flag reaches; it never switches one on. Public ids and slugs,
    # not foreign keys: a deleted user or role must never delete or break the flag row.
    user_ids = models.JSONField(default=list, blank=True)
    role_slugs = models.JSONField(default=list, blank=True)
    tenant_ids = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_feature_flag"
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} ({'enabled' if self.enabled else 'disabled'})"


class LookupValueQuerySet(models.QuerySet):
    def in_set(self, set_key: str):
        return self.filter(set_key=set_key)

    def active(self):
        return self.filter(is_active=True)


class LookupValue(models.Model):
    """
    One value of an admin-editable vocabulary (CONFIGURATION.md § 14). The STABLE key is what
    records store and reports group by; admins edit the label, the order and whether it is active.
    Deactivate, never delete: a value already held by records stays valid and keeps its label.
    """

    set_key = models.CharField(max_length=64, db_index=True)  # declared in code (registry.lookups)
    key = models.SlugField(max_length=64, editable=False)  # stable; never in a writable serializer
    label = models.CharField(max_length=128)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Code refers to it by key (an "other — please specify"): it cannot be deactivated.
    is_system = models.BooleanField(default=False)
    meta = models.JSONField(default=dict, blank=True)  # validated by the set's meta_schema
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = LookupValueQuerySet.as_manager()

    class Meta:
        db_table = "core_lookup_value"
        ordering = ["set_key", "sort_order", "key"]
        constraints = [
            models.UniqueConstraint(fields=["set_key", "key"], name="core_lookup_value_uq")
        ]

    def __str__(self):
        return f"{self.set_key}:{self.key}"


class AppendOnlyError(Exception):
    """A write the audit table refuses by construction (DATA_LIFECYCLE.md § 4.7)."""


class ActivityLogQuerySet(models.QuerySet):
    """Layer 3: ORM bulk writes refuse too. (Layer 4, the Postgres trigger, stops raw SQL.)"""

    def update(self, **kwargs):
        raise AppendOnlyError("core_activity_log is append-only: update() is refused")

    def delete(self):
        raise AppendOnlyError("core_activity_log is append-only: delete() is refused")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AppendOnlyError("core_activity_log is append-only: bulk_update() is refused")


class ActivityLog(models.Model):
    """
    One append-only evidence row (DATA_LIFECYCLE.md § 4.1). Written ONLY by core.audit.record();
    a source scan proves nothing else inserts. No foreign keys, on purpose: a SET_NULL would be an
    UPDATE against evidence, and "who did this" must survive the actor's deletion, so every
    reference is a snapshot (id + label) that still reads correctly on its own.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=False)
    channel = models.CharField(max_length=32)
    action = models.CharField(max_length=64)
    event = models.CharField(max_length=24, default="custom")
    description = models.CharField(max_length=255, blank=True, default="")

    actor_id = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    actor_kind = models.CharField(max_length=24, blank=True, default="")
    actor_label = models.CharField(max_length=255, blank=True, default="")
    consumer_id = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    impersonator_id = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    impersonator_label = models.CharField(max_length=255, blank=True, default="")

    target_type = models.CharField(max_length=100, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    target_repr = models.CharField(max_length=255, blank=True, default="")

    changes = models.JSONField(default=dict, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    batch_id = models.UUIDField(null=True, blank=True)

    source = models.CharField(max_length=16, blank=True, default="")
    via = models.CharField(max_length=16, blank=True, default="")
    origin_os_user = models.CharField(max_length=64, blank=True, default="")
    origin_host = models.CharField(max_length=255, blank=True, default="")
    origin_command = models.CharField(max_length=500, blank=True, default="")

    request_id = models.CharField(max_length=64, blank=True, default="")
    method = models.CharField(max_length=8, blank=True, default="")
    path = models.CharField(max_length=255, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True, default="")

    objects = ActivityLogQuerySet.as_manager()

    class Meta:
        db_table = "core_activity_log"
        ordering = ["-id"]  # id is the sort key: one transaction shares a timestamp, never an id
        indexes = [
            models.Index(fields=["target_type", "target_id", "-id"], name="core_activity_target"),
            models.Index(fields=["actor_id", "-id"], name="core_activity_actor"),
            models.Index(fields=["channel", "-id"], name="core_activity_channel"),
            models.Index(fields=["action"], name="core_activity_action"),
            models.Index(fields=["batch_id"], name="core_activity_batch"),
            models.Index(fields=["created_at"], name="core_activity_created"),
        ]

    def __str__(self):
        return f"{self.action} #{self.pk}"

    def save(self, *args, **kwargs):
        # Layer 2: an existing row is never rewritten. Inserting through save() is the writer's own.
        if not self._state.adding:
            raise AppendOnlyError("core_activity_log is append-only: a saved row cannot change")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("core_activity_log is append-only: delete() is refused")
