"""
ApiConsumer (a system, never a person) and ApiToken (its credential). The token is stored as a
SHA-256 digest only; the plaintext exists in the create response and nowhere else (§ 8).
The service role is the ceiling: a token's scopes narrow it, never widen it (ADR-0016).
"""

import uuid

from django.conf import settings
from django.db import models


class ApiConsumer(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=80, unique=True)  # named after the SYSTEM it serves
    description = models.CharField(max_length=255, blank=True, default="")
    owner_team = models.CharField(max_length=120, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    # The kill switch: outranks every valid token, effective on the next request.
    is_active = models.BooleanField(default=True)
    # PROTECT: deleting a role must never silently widen or drop a machine's access.
    service_role = models.ForeignKey(
        "rbac.Role", on_delete=models.PROTECT, related_name="api_consumers"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "core_api_consumer"
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class ApiToken(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    consumer = models.ForeignKey(ApiConsumer, on_delete=models.CASCADE, related_name="tokens")
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=24, db_index=True)  # the first characters, to spot it
    digest = models.CharField(max_length=64, unique=True)  # sha256 hex of the full token
    scopes = models.JSONField(default=list)  # permission codes, or ["*"]
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    revoked_reason = models.CharField(max_length=255, blank=True, default="")
    rotated_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="successors"
    )

    class Meta:
        db_table = "core_api_token"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.consumer_id}:{self.prefix}"
