"""
The in_app store (NOTIFICATIONS_AND_ALERTING.md § 8). `read_at` is per user; `resolved_at` is
shared (resolving an object closes everyone's open prompt for it); there is ONE open row per
recipient x purpose x object_ref, so a re-run updates the row instead of duplicating it.

Emitters never write these rows: they call notify(), digest() or resolve().
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Notification

TITLE_MAX = 200


def valid_url(url: str) -> bool:
    """A relative deep link: one leading slash, no scheme, no `//`, no backslash or control char."""
    return (
        isinstance(url, str)
        and url.startswith("/")
        and not url.startswith("//")
        and "\\" not in url
        and not any(ord(ch) < 32 for ch in url)
        and len(url) <= 500
    )


def upsert(
    *, recipient_id, purpose, level, title, body="", url="", object_ref="", source_module=""
) -> Notification:
    """The open row for (recipient, purpose, object_ref), created or updated. Without an
    object_ref nothing can be matched, so every call is a new row."""
    fields = {
        "level": level,
        "title": title[:TITLE_MAX],
        "body": body,
        "url": url,
        "source_module": source_module,
        "updated_at": timezone.now(),
    }
    if object_ref:
        open_row = Notification.objects.filter(
            recipient_id=recipient_id,
            purpose_code=purpose,
            object_ref=object_ref,
            resolved_at__isnull=True,
        )
        if open_row.update(**fields):
            return open_row.get()
    try:
        with transaction.atomic():
            return Notification.objects.create(
                recipient_id=recipient_id,
                purpose_code=purpose,
                object_ref=object_ref,
                **fields,
            )
    except IntegrityError:  # a concurrent run created the open row first: update that one
        open_row = Notification.objects.filter(
            recipient_id=recipient_id,
            purpose_code=purpose,
            object_ref=object_ref,
            resolved_at__isnull=True,
        )
        open_row.update(**fields)
        return open_row.get()


def digest(
    purpose,
    recipient_id,
    object_ref,
    title,
    count,
    *,
    resurface=True,
    level="info",
    url="",
    body="",
    source_module="",
) -> Notification:
    """One evolving row ("12 pending changes"). resurface=True marks it unread again WITHOUT
    changing its id, so a client that raises an OS notification per new id fires once. Pass
    resurface=False when the count shrinks: fewer things to do is not news."""
    row = upsert(
        recipient_id=recipient_id,
        purpose=purpose,
        level=level,
        title=title,
        body=body,
        url=url,
        object_ref=object_ref,
        source_module=source_module,
    )
    updates = {"count": count}
    if resurface:
        updates["read_at"] = None
    Notification.objects.filter(pk=row.pk).update(**updates)
    row.refresh_from_db()
    return row


def resolve(object_ref: str, *, by=None, note: str = "") -> int:
    """The item was handled: close every open row for it, for every recipient."""
    if not object_ref:
        return 0
    return Notification.objects.filter(object_ref=object_ref, resolved_at__isnull=True).update(
        resolved_at=timezone.now(), resolved_by=by, resolved_note=note[:500]
    )


def resolve_one(row: Notification) -> None:
    """A row with no object_ref has no subject to share: resolving closes just this row."""
    Notification.objects.filter(pk=row.pk, resolved_at__isnull=True).update(
        resolved_at=timezone.now()
    )


def mark_read(user, row: Notification) -> None:
    Notification.objects.filter(pk=row.pk, recipient=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )


def mark_all_read(user, up_to_id: int) -> int:
    """Marks only what the user has seen: a row that arrived mid-click stays unread."""
    return Notification.objects.filter(
        recipient=user, read_at__isnull=True, id__lte=up_to_id
    ).update(read_at=timezone.now())


def summary(user) -> dict:
    own = Notification.objects.filter(recipient=user)
    return {
        "unread": own.filter(read_at__isnull=True).count(),
        "open_actions": own.filter(
            level=Notification.Level.ACTION, resolved_at__isnull=True
        ).count(),
        "latest_id": own.order_by("-id").values_list("id", flat=True).first() or 0,
    }
