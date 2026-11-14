"""
GuardedEmailBackend: outside production, no mail reaches a real person (§ 27).

config/settings.py makes it EMAIL_BACKEND whenever core.env.outbound_guard_active(APP_ENV), and
the configured backend becomes EMAIL_BACKEND_INNER, which this wraps. So a backend chosen at
runtime is covered as well.

- NONPROD_TEST_RECIPIENT set: every message goes to that one address. Cc and Bcc are removed, the
  subject is prefixed "[<APP_ENV> TEST]", and the original recipients go into an
  X-Original-Recipients header. Alternatives and attachments travel unchanged (the message is
  copied, never rebuilt).
- No test recipient: only a log-only inner backend (console, file, locmem, dummy) may run. Any
  other backend (SMTP, a provider) is refused: nothing is sent, a WARNING is logged, and
  dbx.http.E011 reports the configuration.
"""

import copy
import logging

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend

from core.env import outbound_guard_active

from .policy import is_log_only

logger = logging.getLogger("core.mail")


def redirected(message, recipient: str, app_env: str):
    """A copy of `message` addressed only to `recipient`; the original is untouched."""
    original = [*message.to, *message.cc, *message.bcc]
    copied = copy.copy(message)
    copied.to, copied.cc, copied.bcc = [recipient], [], []
    copied.subject = f"[{app_env or 'unset'} TEST] {message.subject}"
    copied.extra_headers = {
        **(message.extra_headers or {}),
        "X-Original-Recipients": ", ".join(original),
    }
    return copied


class GuardedEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.inner_path = settings.EMAIL_BACKEND_INNER
        self.inner = get_connection(self.inner_path, fail_silently=fail_silently, **kwargs)

    def _refuses(self) -> bool:
        """No test recipient and a backend that would really deliver: nothing may leave."""
        return (
            outbound_guard_active(settings.APP_ENV)
            and not (getattr(settings, "NONPROD_TEST_RECIPIENT", "") or "").strip()
            and not is_log_only(self.inner_path)
        )

    def open(self):
        # `with get_connection() as c:` opens first: an SMTP login is already outbound.
        return None if self._refuses() else self.inner.open()

    def close(self):
        return self.inner.close()

    def send_messages(self, email_messages):
        messages = list(email_messages or [])
        if not messages:
            return 0
        app_env = settings.APP_ENV
        if not outbound_guard_active(app_env):
            return self.inner.send_messages(messages)
        recipient = (getattr(settings, "NONPROD_TEST_RECIPIENT", "") or "").strip()
        if recipient:
            return self.inner.send_messages([redirected(m, recipient, app_env) for m in messages])
        if not self._refuses():
            return self.inner.send_messages(messages)
        logger.warning(
            "core.mail.blocked_locally",
            extra={"count": len(messages), "backend": self.inner_path, "app_env": app_env},
        )
        return 0
