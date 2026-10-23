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
