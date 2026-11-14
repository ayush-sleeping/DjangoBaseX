"""
Email rendering and the one place an email message is built and sent (NOTIFICATIONS_AND_ALERTING.md
§ 11). Three files per message: `<name>.subject.txt`, `<name>.txt`, `<name>.html`. Subjects render
with autoescape OFF and newlines stripped (a newline in a subject is header injection). Links come
from FRONTEND_BASE_URL through frontend_url(), never from the request's Host header.

Only core.notifications' email channel and send_email() build a message; an architecture test
(tests/architecture/test_no_direct_transport_use.py) keeps it that way.
"""

import logging
import re
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Context, engines

logger = logging.getLogger("core.mail")

DEFAULT_MAX_RECIPIENTS = 20


class EmailRenderError(Exception):
    """A template is missing or broken: nothing was sent."""


def frontend_url(path: str, **query: str) -> str:
    """An absolute link into the web app. The base is settings.FRONTEND_BASE_URL, always."""
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    return f"{url}?{urlencode(query)}" if query else url


def _render(name: str, context: dict, *, autoescape: bool) -> str:
    engine = engines["django"].engine
    return engine.get_template(name).render(Context(context, autoescape=autoescape))


def render_email(template: str, context: dict) -> tuple[str, str, str]:
    """(subject, text, html) for `template` ("app/email/name"). A `link_path` in the context
    becomes `link`, with `token` as its only query value."""
    context = dict(context)
    if context.get("link_path"):
        query = {"token": context["token"]} if context.get("token") else {}
        context["link"] = frontend_url(str(context["link_path"]), **query)
    try:
        subject = _render(f"{template}.subject.txt", context, autoescape=False)
        text = _render(f"{template}.txt", context, autoescape=True)
        html = _render(f"{template}.html", context, autoescape=True)
    except Exception as exc:  # noqa: BLE001 — a template error is a classified result, not a 500
        raise EmailRenderError(type(exc).__name__) from None
    return re.sub(r"[\r\n]+", " ", subject).strip(), text, html


def compose(subject: str, text: str, html: str, to: str, *, reply_to: str = ""):
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        to=[to],
        reply_to=[reply_to] if reply_to else None,
        headers={"Auto-Submitted": "auto-generated"},
    )
    message.attach_alternative(html, "text/html")
    return message


def send_email(template: str, to, context: dict, *, reply_to: str = "") -> bool:
    """One message per recipient, at most EMAIL_MAX_RECIPIENTS. True only when every send
    returned without an error; never raises. A failure logs the recipient and subject, never the
    body (it may hold a single-use link)."""
    recipients = [to] if isinstance(to, str) else list(to)
    cap = getattr(settings, "EMAIL_MAX_RECIPIENTS", DEFAULT_MAX_RECIPIENTS)
    if not recipients or len(recipients) > cap:
        logger.error("core.mail.recipient_count", extra={"count": len(recipients), "cap": cap})
        return False
    ok = True
    for address in recipients:
        subject = ""
        try:
            subject, text, html = render_email(template, context)
            compose(subject, text, html, address, reply_to=reply_to).send()
        except Exception:  # noqa: BLE001 — returns False, by contract
            logger.error("core.mail.send_failed", extra={"to": address, "subject": subject})
            ok = False
    return ok
