"""
Setting overrides (CONFIGURATION.md § 9.2). A row exists only where an admin changed a value at a
scope; absence means the code default. What a setting IS (its type, label, default) lives in code,
in registry.settings, never here. Read and write through core.settings_service only.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


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


class JobScheduleQuerySet(models.QuerySet):
    def for_jobs(self, names):
        return self.filter(job_name__in=names)


class JobSchedule(models.Model):
    """
    Which django-celery-beat rows the job registry owns (JOBS_AND_INTEGRATIONS.md § 6). The schedule
    sync creates, updates and deletes ONLY rows listed here: ownership is recorded, never inferred
    from a task-name prefix, so a row an operator added by hand is never touched.
    """

    job_name = models.CharField(max_length=128, unique=True)
    periodic_task = models.OneToOneField(
        "django_celery_beat.PeriodicTask", on_delete=models.CASCADE, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = JobScheduleQuerySet.as_manager()

    class Meta:
        db_table = "core_job_schedule"
        ordering = ["job_name"]

    def __str__(self):
        return self.job_name


class JobRunQuerySet(models.QuerySet):
    def for_job(self, name: str):
        return self.filter(job_name=name)

    def terminal(self):
        return self.filter(status__in=JobRun.TERMINAL)

    def queued(self):
        return self.filter(status=JobRun.Status.QUEUED)

    def started_since(self, moment):
        return self.filter(started_at__gte=moment)

    def failed(self):
        return self.filter(status=JobRun.Status.FAILED)


class JobRun(models.Model):
    """
    One execution of one job, from queued to a terminal state (JOBS_AND_INTEGRATIONS.md § 7).
    Written only by core.jobs.recorder, through the "monitor" database alias, and never raising.
    The error is type + scrubbed message, never a traceback.
    """

    class Trigger(models.TextChoices):
        SCHEDULE = "schedule"
        ON_DEMAND = "on_demand"
        MANUAL = "manual"
        RETRY = "retry"

    class Status(models.TextChoices):
        QUEUED = "queued"
        STARTED = "started"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        RETRYING = "retrying"
        REVOKED = "revoked"
        DEAD = "dead"  # an unknown or unregistered task name: it can only fail
        SKIPPED = "skipped"  # single-flight: another run held the lock (§ 9); not a failure

    TERMINAL = ("succeeded", "failed", "revoked", "dead", "skipped")

    task_id = models.CharField(max_length=64, unique=True)
    job_name = models.CharField(max_length=150, db_index=True)
    queue = models.CharField(max_length=64, blank=True, default="")
    trigger = models.CharField(max_length=16, choices=Trigger.choices, default=Trigger.SCHEDULE)
    status = models.CharField(max_length=16, choices=Status.choices)
    attempt = models.PositiveSmallIntegerField(default=0)
    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)  # perf_counter, in the worker
    count = models.IntegerField(null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True, default="")
    error_type = models.CharField(max_length=200, blank=True, default="")
    error_message = models.TextField(blank=True, default="")  # ≤ 2 000 characters, scrubbed
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    idempotency_key = models.CharField(max_length=200, blank=True, default="")

    objects = JobRunQuerySet.as_manager()

    class Meta:
        db_table = "core_job_run"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["job_name", "-started_at"], name="core_jobrun_job_started"),
            models.Index(fields=["status", "queued_at"], name="core_jobrun_status_queued"),
        ]

    def __str__(self):
        return f"{self.job_name} {self.status} #{self.pk}"


class JobState(models.Model):
    """
    A resumable job's cursor (JOBS_AND_INTEGRATIONS.md § 11): a database row, never the cache,
    which a deploy clears. Shared by reconcilers and, later, digests.
    """

    name = models.CharField(max_length=150, unique=True)
    cursor = models.JSONField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_job_state"
        ordering = ["name"]

    def __str__(self):
        return self.name


class FindingQuerySet(models.QuerySet):
    def open(self):
        return self.filter(resolved_at__isnull=True)

    def of(self, kind: str, object_type: str, object_id: str):
        return self.filter(kind=kind, object_type=object_type, object_id=object_id)


class Finding(models.Model):
    """
    Something a machine noticed and a human must decide (DOMAIN_PRIMITIVES.md § 8). One OPEN row
    per (kind, object): a re-detection touches it. Resolved rows are history; a recurrence opens a
    new row. Written only through core.findings. object_type/object_id are snapshots, as in the
    audit log, never foreign keys: the finding outlives what it is about.
    """

    kind = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=16)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    occurrences = models.PositiveIntegerField(default=1)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolution = models.CharField(max_length=32, blank=True, default="")
    resolution_note = models.TextField(blank=True, default="")

    objects = FindingQuerySet.as_manager()

    class Meta:
        db_table = "core_finding"
        ordering = ["-last_seen_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "object_type", "object_id"],
                condition=models.Q(resolved_at__isnull=True),
                name="core_finding_open_uq",
            )
        ]
        indexes = [models.Index(fields=["kind", "resolved_at"], name="core_finding_kind_open")]

    def __str__(self):
        return f"{self.kind} {self.object_type}:{self.object_id}"


class OutboxQuerySet(models.QuerySet):
    def due(self, now):
        return self.filter(
            status__in=(OutboxMessage.Status.PENDING, OutboxMessage.Status.RETRY),
            next_attempt_at__lte=now,
        )

    def stale_leases(self, now):
        return self.filter(status=OutboxMessage.Status.LEASED, leased_until__lt=now)


class OutboxMessage(models.Model):
    """
    "We owe the world this message", committed with the change that decided it
    (JOBS_AND_INTEGRATIONS.md § 12). Written by core.outbox.enqueue; moved only by the drainer
    and the lease-recovery sweep, each by compare-and-set on (status, locked_by).
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        LEASED = "leased"  # claimed by a drainer; recovered by core.outbox_recover when stale
        RETRY = "retry"
        SENT = "sent"
        SKIPPED = "skipped"  # intentionally not sent (re-validated, or not configured)
        FAILED = "failed"  # the dead letter
        UNKNOWN = "unknown"  # may or may not have been sent: terminal and human-owned

    # Covered by a reconciler (tests/architecture/test_every_pending_state_has_a_reconciler.py).
    TRANSIENT_STATES = ("leased",)

    topic = models.CharField(max_length=100, db_index=True)
    dedupe_key = models.CharField(max_length=255, unique=True)
    payload = models.JSONField(default=dict)  # ids and scalars only
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)  # every attempt, the first included
    max_attempts = models.PositiveSmallIntegerField()
    next_attempt_at = models.DateTimeField()
    leased_until = models.DateTimeField(null=True, blank=True)
    # The lease token: "<host>:<pid>:<random>". A result is written only while it still matches.
    locked_by = models.CharField(max_length=100, blank=True, default="")
    last_error_code = models.CharField(max_length=100, blank=True, default="")
    last_error_message = models.TextField(blank=True, default="")  # ≤ 1 000 characters, scrubbed
    result_ref = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    objects = OutboxQuerySet.as_manager()

    class Meta:
        db_table = "core_outbox"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="core_outbox_due"),
            models.Index(fields=["status", "leased_until"], name="core_outbox_lease"),
        ]

    def __str__(self):
        return f"{self.topic} {self.status} #{self.pk}"


# --- Webhooks (BUILD_ORDER 7.6; JOBS_AND_INTEGRATIONS.md § 16, § 17) -----------------------------


class WebhookEndpoint(models.Model):
    """
    A URL that receives signed, ids-only event callbacks. Owned by an API consumer when `consumer`
    is set, else platform-owned. The signing secret is encrypted, not hashed: we must reproduce it
    to sign. It is shown once, at creation or rotation.
    `is_active` is a human switch; `disabled_at` is the circuit breaker's. They are separate columns
    because "an admin turned it off" and "it tripped" need different fixes.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    url = models.URLField(max_length=2048)
    secret_ciphertext = models.TextField()
    previous_secret_ciphertext = models.TextField(blank=True, default="")
    previous_secret_expires_at = models.DateTimeField(null=True, blank=True)
    timeout_seconds = models.PositiveSmallIntegerField(default=10)
    custom_headers = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    # The owning system (TECH_DEBT DB-79): NULL = platform-owned. Never a person.
    consumer = models.ForeignKey(
        "core.ApiConsumer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="webhook_endpoints",
    )
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_webhook_endpoint"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.name} #{self.pk}"


class WebhookSubscription(models.Model):
    """A real table, not a JSON list: matching an event is an indexed join (and works on SQLite)."""

    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="subscriptions"
    )
    event = models.CharField(max_length=100)

    class Meta:
        db_table = "core_webhook_subscription"
        constraints = [
            models.UniqueConstraint(fields=["endpoint", "event"], name="core_webhook_sub_unique")
        ]
        indexes = [models.Index(fields=["event"], name="core_webhook_sub_event")]

    def __str__(self):
        return f"{self.event} -> endpoint #{self.endpoint_id}"


class WebhookDelivery(models.Model):
    """One event x endpoint. The row is the delivery log; the outbox row that carries it is the
    durable obligation, so `pending` is watched by the outbox's drainer and recovery sweep."""

    class Status(models.TextChoices):
        PENDING = "pending"
        DELIVERED = "delivered"
        FAILED = "failed"

    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    event = models.CharField(max_length=100)
    event_id = models.CharField(max_length=64)
    delivery_id = models.CharField(max_length=64)  # stable per event x endpoint; sent to receivers
    payload = models.JSONField(default=dict)  # ids only
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True, default="")  # first 2 000 characters
    error_code = models.CharField(max_length=100, blank=True, default="")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    is_test = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_webhook_delivery"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "delivery_id"], name="core_webhook_dlv_unique"
            )
        ]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="core_webhook_dlv_due")]

    def __str__(self):
        return f"{self.event} {self.status} #{self.pk}"


class InboundWebhookEvent(models.Model):
    """A verified callback from a third party, stored before it is processed (§ 17). The unique
    `dedupe_key` is the idempotency claim, taken only AFTER the signature is proven."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        PROCESSED = "processed"
        FAILED = "failed"
        IGNORED = "ignored"

    provider = models.CharField(max_length=64)
    delivery_id = models.CharField(max_length=255)
    dedupe_key = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=128, blank=True, default="")
    payload = models.JSONField(default=dict)  # minimised: the verifier's allowlist, never the body
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=100, blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_inbound_webhook_event"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["provider", "received_at"], name="core_inbound_wh_provider")
        ]

    def __str__(self):
        return f"{self.provider} {self.status} #{self.pk}"


# --- Notifications (BUILD_ORDER 7.7; NOTIFICATIONS_AND_ALERTING.md Part A) ------------------------


class NotificationRoute(models.Model):
    """Where a BROADCAST purpose goes on a channel: admin-editable data, never a call-site literal
    (§ 1). `target` is validated per channel by core.notifications.service (email: addresses)."""

    purpose_code = models.CharField(max_length=100, db_index=True)
    channel = models.CharField(max_length=32)
    target = models.JSONField(default=dict)
    target_hash = models.CharField(max_length=64, editable=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_notification_route"
        ordering = ["purpose_code", "channel", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["purpose_code", "channel", "target_hash"], name="core_notif_route_unique"
            )
        ]

    def __str__(self):
        return f"{self.purpose_code} -> {self.channel} #{self.pk}"


class NotificationSetting(models.Model):
    """The event x channel matrix cell (§ 4). Seeded from code, never overwritten by a sync."""

    purpose_code = models.CharField(max_length=100)
    channel = models.CharField(max_length=32)
    enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_notification_setting"
        constraints = [
            models.UniqueConstraint(
                fields=["purpose_code", "channel"], name="core_notif_setting_unique"
            )
        ]

    def __str__(self):
        return f"{self.purpose_code}/{self.channel} {'on' if self.enabled else 'off'}"


class NotificationPurposeState(models.Model):
    """Per-purpose test routing (§ 6): seeded ON for `rollout` purposes, flipped off by an admin."""

    purpose_code = models.CharField(max_length=100, unique=True)
    test_routing = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_notification_purpose_state"

    def __str__(self):
        return f"{self.purpose_code} test_routing={self.test_routing}"


class NotificationPreference(models.Model):
    """A user's choice (user set) or the system default for everyone who has not chosen (user
    null), per purpose x channel (§ 5)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    purpose_code = models.CharField(max_length=100)
    channel = models.CharField(max_length=32)
    enabled = models.BooleanField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_notification_preference"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "purpose_code", "channel"],
                condition=models.Q(user__isnull=False),
                name="core_notif_pref_user_unique",
            ),
            # A plain unique over a nullable column would allow unlimited system rows.
            models.UniqueConstraint(
                fields=["purpose_code", "channel"],
                condition=models.Q(user__isnull=True),
                name="core_notif_pref_system_unique",
            ),
        ]

    def __str__(self):
        return f"{self.purpose_code}/{self.channel} user={self.user_id}"


class NotificationDelivery(models.Model):
    """The delivery log (§ 7): one row per purpose x channel x recipient, including every skip
    with its reason. `pending` is watched by its outbox row (notifications.deliver). Never holds a
    token or a provider body: an error is a code plus a scrubbed, truncated message."""

    class Status(models.TextChoices):
        PENDING = "pending"
        SENT = "sent"
        SKIPPED = "skipped"
        FAILED = "failed"
        UNKNOWN = "unknown"

    purpose_code = models.CharField(max_length=100)
    channel = models.CharField(max_length=32)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    route = models.ForeignKey(
        NotificationRoute, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    target = models.JSONField(default=dict, blank=True)  # a broadcast address; empty for a user
    target_hash = models.CharField(max_length=64)
    dedupe_key = models.CharField(max_length=255, blank=True, default="")
    object_ref = models.CharField(max_length=200, blank=True, default="")
    context = models.JSONField(default=dict, blank=True)  # scalars; never for a token purpose
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    skip_reason = models.CharField(max_length=64, blank=True, default="")
    provider_ref = models.CharField(max_length=200, blank=True, default="")
    error_code = models.CharField(max_length=100, blank=True, default="")
    error_message = models.CharField(max_length=1000, blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    is_test = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_notification_delivery"
        ordering = ["-id"]
        constraints = [
            # Reminder dedupe lives in the delivery table and fails closed (§ 7).
            models.UniqueConstraint(
                fields=["purpose_code", "channel", "target_hash", "dedupe_key"],
                condition=~models.Q(dedupe_key=""),
                name="core_notif_dlv_dedupe",
            )
        ]
        indexes = [models.Index(fields=["purpose_code", "status"], name="core_notif_dlv_purpose")]

    def __str__(self):
        return f"{self.purpose_code}/{self.channel} {self.status} #{self.pk}"


class Notification(models.Model):
    """The in_app store (§ 8): per-user read state, shared resolved state, one open row per
    recipient x purpose x object_ref."""

    class Level(models.TextChoices):
        INFO = "info"
        SUCCESS = "success"
        WARNING = "warning"
        ERROR = "error"
        ACTION = "action"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    purpose_code = models.CharField(max_length=100)
    source_module = models.CharField(max_length=64, blank=True, default="")
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.INFO)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    url = models.CharField(max_length=500, blank=True, default="")
    object_ref = models.CharField(max_length=200, blank=True, default="", db_index=True)
    count = models.PositiveIntegerField(default=1)
    read_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "core_notification"
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "purpose_code", "object_ref"],
                condition=models.Q(resolved_at__isnull=True) & ~models.Q(object_ref=""),
                name="core_notif_one_open_row",
            )
        ]
        indexes = [
            models.Index(fields=["recipient", "read_at"], name="core_notif_unread"),
            models.Index(fields=["recipient", "-updated_at"], name="core_notif_recent"),
        ]

    def __str__(self):
        return f"{self.purpose_code} for user #{self.recipient_id}"


# --- Ops alerting (BUILD_ORDER 7.8; NOTIFICATIONS_AND_ALERTING.md Part B) ------------------------


class OpsDigestRun(models.Model):
    """One ops digest: the stamp that says which held alerts it carried (§ 16). `pending` means
    handed to notify() and not yet settled; core.ops.digest settles it from the delivery log at the
    start of every run (sent | unknown | failed). Only a sent or unknown run releases its alerts: a
    failed one gives them back, so a digest that did not arrive never makes its contents vanish."""

    class Status(models.TextChoices):
        PENDING = "pending"
        SENT = "sent"
        UNKNOWN = "unknown"
        FAILED = "failed"

    slot_at = models.DateTimeField()  # the scheduled digest time this run answers (UTC)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    held_count = models.PositiveIntegerField(default=0)
    incident_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_ops_digest_run"
        ordering = ["-id"]
        indexes = [models.Index(fields=["status", "slot_at"], name="core_ops_digest_slot")]

    def __str__(self):
        return f"ops digest {self.slot_at:%Y-%m-%d %H:%M} {self.status}"


class OpsAlert(models.Model):
    """The ops alert ledger (§ 14): one row per dispatcher call, with its decision and reason.
    Cooldowns, dedupe and "since the last digest" are queries on this table, never the cache."""

    class Decision(models.TextChoices):
        SENT = "sent"  # handed to notify(); the delivery log holds the provider's answer
        HELD = "held"  # waiting for a digest or for quiet hours to end
        SKIPPED = "skipped"  # cooldown, disabled, no destination, duplicate, dispatch error

    class Event(models.TextChoices):
        PROBLEM = "problem"
        RECOVERED = "recovered"

    source = models.CharField(max_length=64)
    reason = models.CharField(max_length=100)
    kind = models.CharField(max_length=32)
    event = models.CharField(max_length=16, choices=Event.choices, default=Event.PROBLEM)
    subject_key = models.CharField(max_length=255)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    decision = models.CharField(max_length=16, choices=Decision.choices)
    decision_reason = models.CharField(max_length=64, blank=True, default="")
    channel = models.CharField(max_length=32, blank=True, default="")
    released_at = models.DateTimeField(null=True, blank=True)
    released_via = models.CharField(max_length=32, blank=True, default="")
    digest_run = models.ForeignKey(
        OpsDigestRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "core_ops_alert"
        ordering = ["-id"]
        indexes = [
            models.Index(
                fields=["subject_key", "decision", "created_at"], name="core_ops_alert_subject"
            ),
            models.Index(fields=["decision", "released_at"], name="core_ops_alert_held"),
        ]

    def __str__(self):
        return f"{self.subject_key} {self.decision}:{self.decision_reason}"


class Incident(models.Model):
    """A condition a monitor reported (§ 17): announced once when it opens, once when it recovers.
    `pending` waits out confirm_after_minutes, so a flap inside it is never announced."""

    class Status(models.TextChoices):
        PENDING = "pending"
        OPEN = "open"
        RECOVERED = "recovered"

    source = models.CharField(max_length=64)
    key = models.CharField(max_length=255)
    label = models.CharField(max_length=300)
    kind = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    first_seen_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    announced_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField()
    recovered_at = models.DateTimeField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "core_health_incident"
        ordering = ["-first_seen_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "key"],
                condition=~models.Q(status="recovered"),
                name="core_incident_one_live",
            )
        ]

    def __str__(self):
        return f"{self.source}/{self.key} {self.status}"


# Registered under the core app, defined in core.api_tokens (one concern per package).
from core.api_tokens.models import ApiConsumer, ApiToken  # noqa: E402, F401


class PrivateFile(models.Model):
    """An uploaded file's record. The bytes live in private storage with a generated name; the only
    way to read them is the permission-checked download view (core.files, API_PLATFORM.md § 19)."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    purpose = models.CharField(max_length=64)
    original_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)  # sniffed from the bytes, never the client's
    size = models.PositiveBigIntegerField()
    storage_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_private_file"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.purpose}:{self.public_id}"
