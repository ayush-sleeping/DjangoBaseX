"""
Business logic for enquiries (AGENTS.md § 3). Views call these and only these; every write runs in
a transaction and audits what it changed. Status changes go through the state machine only.
"""

from django.db import transaction

from core.sdk import log_activity, reserve_number, stamp_provenance, to_money, transition

from .models import Enquiry
from .wiring import SERIES


def create_enquiry(
    *,
    actor,
    contact_name: str,
    contact_email: str,
    subject: str,
    value_amount,
    value_currency: str,
    message: str = "",
    source_ref: str | None = None,
) -> Enquiry:
    value = to_money(value_amount, value_currency)  # UnknownCurrency for a code money can't hold
    with transaction.atomic():
        enquiry = Enquiry.objects.create(
            number=reserve_number(SERIES.key),
            owner=actor,
            contact_name=contact_name,
            contact_email=contact_email,
            subject=subject,
            message=message,
            value_amount=value.amount,
            value_currency=value.currency,
            **stamp_provenance(actor=actor, source_ref=source_ref),
        )
    log_activity("enquiries.enquiry.created", actor=actor, target=enquiry)
    return enquiry


def update_enquiry(*, actor, enquiry: Enquiry, **changes) -> Enquiry:
    if "value_amount" in changes or "value_currency" in changes:
        value = to_money(
            changes.pop("value_amount", enquiry.value_amount),
            changes.pop("value_currency", enquiry.value_currency),
        )
        changes |= {"value_amount": value.amount, "value_currency": value.currency}
    with transaction.atomic():
        for name, value in changes.items():
            setattr(enquiry, name, value)
        enquiry.save(update_fields=[*changes, "updated_at"])
    log_activity("enquiries.enquiry.updated", actor=actor, target=enquiry, fields=sorted(changes))
    return enquiry


def move_enquiry(*, actor, enquiry: Enquiry, to: str, reason: str = "") -> Enquiry:
    """Raises IllegalTransition or ReasonRequired; the state machine records the history."""
    transition(enquiry, "status", to, actor=actor, reason=reason)
    return enquiry


def delete_enquiry(*, actor, enquiry: Enquiry) -> None:
    """Bins the enquiry (restorable from the recycle bin); its number is never reused."""
    with transaction.atomic():
        enquiry.soft_delete(actor=actor)
    log_activity("enquiries.enquiry.deleted", actor=actor, target=enquiry)
