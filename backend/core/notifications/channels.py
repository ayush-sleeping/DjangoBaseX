"""
Channel adapters (NOTIFICATIONS_AND_ALERTING.md § 2): a transport knows how to render and deliver
one message and nothing about purposes, preferences or policy. `render` and `send` never raise
into their caller: a failure is a DeliveryResult. The engine is the only caller (an architecture
test bans every other import of this module and of the mail layer's send path).
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings

from core.mail import render as mail

from . import inapp

logger = logging.getLogger("core.notifications")

ACCEPTED, REJECTED, RETRY, UNKNOWN = "accepted", "rejected", "retry", "unknown"


@dataclass(frozen=True)
class DeliveryResult:
    """accepted(ref) | rejected(code): permanent | retry(after): transient, nothing was sent |
    unknown: the provider may have accepted it, so it is never resent."""

    status: str
    ref: str = ""
    code: str = ""
    after: float | None = None

    @classmethod
    def accepted(cls, ref=""):
        return cls(ACCEPTED, ref=ref)

    @classmethod
    def rejected(cls, code):
        return cls(REJECTED, code=code)

    @classmethod
    def retry(cls, code, after=None):
        return cls(RETRY, code=code, after=after)

    @classmethod
    def unknown(cls, code):
        return cls(UNKNOWN, code=code)


@dataclass(frozen=True)
class RenderedMessage:
    purpose: str
    channel: str
    recipient_id: int | None = None
    address: str = ""
    subject: str = ""
    text: str = ""
    html: str = ""
    title: str = ""
    body: str = ""
    url: str = ""
    object_ref: str = ""
    level: str = "info"
    source_module: str = ""
    extra: dict = field(default_factory=dict)


class EmailChannel:
    key = "email"

    def available(self) -> bool:
        return bool(getattr(settings, "EMAIL_BACKEND", ""))

    def render(self, purpose, context, *, recipient, address, test=False):
        if not purpose.template:
            return DeliveryResult.rejected("no_template")
        if not address:
            return DeliveryResult.rejected("no_address")
        data = dict(context)
        if recipient is not None:
            data.setdefault("user", recipient)
        try:
            subject, text, html = mail.render_email(purpose.template, data)
        except mail.EmailRenderError as exc:
            return DeliveryResult.rejected(f"render_failed:{exc}"[:100])
        if test:
            subject = f"[TEST] {subject}"
        return RenderedMessage(
            purpose.code,
            self.key,
            getattr(recipient, "pk", None),
            address,
            subject=subject,
            text=text,
            html=html,
        )

    def send(self, message: RenderedMessage) -> DeliveryResult:
        try:
            mail.compose(message.subject, message.text, message.html, message.address).send()
        except Exception:  # noqa: BLE001 — the provider may have accepted it: unknown, not retried
            return DeliveryResult.unknown("send_error")
        return DeliveryResult.accepted()


class InAppChannel:
    key = "in_app"

    def available(self) -> bool:
        return True

    def render(self, purpose, context, *, recipient, address, test=False):
        if recipient is None:
            return DeliveryResult.rejected("no_recipient")
        url = str(context.get("url") or "")
        if url and not inapp.valid_url(url):
            return DeliveryResult.rejected("invalid_url")
        title = str(context.get("title") or purpose.label)
        return RenderedMessage(
            purpose.code,
            self.key,
            recipient.pk,
            title=f"[TEST] {title}" if test else title,
            body=str(context.get("body") or purpose.description),
            url=url,
            object_ref="" if test else str(context.get("object_ref") or ""),
            level=purpose.level,
            source_module=purpose.owner_module,
        )

    def send(self, message: RenderedMessage) -> DeliveryResult:
        try:
            row = inapp.upsert(
                recipient_id=message.recipient_id,
                purpose=message.purpose,
                level=message.level,
                title=message.title,
                body=message.body,
                url=message.url,
                object_ref=message.object_ref,
                source_module=message.source_module,
            )
        except Exception:  # noqa: BLE001 — the row was not written, so it is safe to retry
            return DeliveryResult.retry("store_error")
        return DeliveryResult.accepted(str(row.public_id))


EMAIL = EmailChannel()
IN_APP = InAppChannel()
