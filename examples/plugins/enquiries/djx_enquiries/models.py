"""
Enquiries: the second product's one model (BUILD_ORDER 10.1).

Tables are enquiries_…, with Meta.db_table explicit. Rows are reached only through
Enquiry.objects.visible_to(user), which fails closed (ADR-0011). `status` moves only through the
registered state machine (wiring.MACHINE); `number` is minted by the numbering series.
"""

import uuid

from django.conf import settings
from django.db import models

from core.sdk import (
    ProvenanceModel,
    SoftDeleteModel,
    SoftDeleteQuerySet,
    VisibleToQuerySet,
    money_fields,
    money_property,
    soft_delete_managers,
)


class EnquiryQuerySet(SoftDeleteQuerySet, VisibleToQuerySet):
    def visible_to(self, user):
        """A person sees the enquiries they own; a superuser sees all; anyone else, nothing."""
        if user is None or not user.is_authenticated:
            return self.none()
        if user.is_superuser:
            return self.all()
        return self.filter(owner=user)


class Enquiry(SoftDeleteModel, ProvenanceModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUOTED = "quoted", "Quoted"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.CharField(max_length=32, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    contact_name = models.CharField(max_length=200)
    contact_email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    # Required by product choice: money_fields(optional=True) + money_pair_check() would relax it.
    value_amount, value_currency = money_fields()
    value = money_property("value")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects, all_objects = soft_delete_managers(EnquiryQuerySet)

    class Meta:
        db_table = "enquiries_enquiry"
        ordering = ["-created_at", "-pk"]
        constraints = [
            # The numbering backstop (DOMAIN_PRIMITIVES § 2): a minted number is never reused.
            models.UniqueConstraint(fields=["number"], name="enquiries_enquiry_number_uq"),
            models.CheckConstraint(
                condition=models.Q(status__in=["new", "contacted", "quoted", "won", "lost"]),
                name="enquiries_enquiry_status_ck",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.subject}"
