"""
The non-production guard for mail (JOBS_AND_INTEGRATIONS.md § 27). Done when: in development no
mail leaves the machine except to the test recipient. Each delivery-path test has a control that
patches the guard out and shows the leak it would otherwise catch.

pytest-django swaps EMAIL_BACKEND for locmem in its test environment, so these tests set the
guarded backend explicitly, exactly as config/settings.py does outside production.
"""

import smtplib

import pytest
from django.core import mail
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection, send_mail

from core import checks, config_audit
from core.env import outbound_guard_active
from core.mail import backends
from core.mail.policy import GUARDED_BACKEND

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"
SMTP = "django.core.mail.backends.smtp.EmailBackend"


@pytest.fixture
def guarded(settings):
    settings.APP_ENV = "development"
    settings.EMAIL_BACKEND = GUARDED_BACKEND
    settings.EMAIL_BACKEND_INNER = LOCMEM
    settings.NONPROD_TEST_RECIPIENT = "qa@example.test"
    return settings


@pytest.fixture
def no_smtp(monkeypatch):
    """Any SMTP connection fails the test: nothing may dial a relay."""
    opened = []

    class Refused(smtplib.SMTP):
        def __init__(self, *args, **kwargs):
            opened.append(args)
            raise AssertionError("an SMTP connection was opened")

    monkeypatch.setattr(smtplib, "SMTP", Refused)
    monkeypatch.setattr(smtplib, "SMTP_SSL", Refused)
    return opened


def test_every_message_goes_to_the_test_recipient_only(guarded):
    message = EmailMessage(
        "Your invoice",
        "Hello",
        "from@example.test",
        to=["customer@real.example"],
        cc=["boss@real.example"],
        bcc=["audit@real.example"],
    )
    assert message.send() == 1
    (sent,) = mail.outbox
    assert (sent.to, sent.cc, sent.bcc) == (["qa@example.test"], [], [])
    assert sent.subject == "[development TEST] Your invoice"
    assert sent.extra_headers["X-Original-Recipients"] == (
        "customer@real.example, boss@real.example, audit@real.example"
    )
    assert sent.recipients() == ["qa@example.test"]
    assert message.to == ["customer@real.example"]  # the caller's message is untouched


def test_alternatives_and_attachments_travel_with_the_redirect(guarded):
    message = EmailMultiAlternatives("Report", "text", "from@example.test", ["a@real.example"])
    message.attach_alternative("<p>html</p>", "text/html")
    message.attach("report.csv", "a,b\n1,2\n", "text/csv")
    message.send()
    (sent,) = mail.outbox
    assert sent.to == ["qa@example.test"]
    assert sent.alternatives[0][0] == "<p>html</p>"
    assert sent.attachments[0][0] == "report.csv"
    assert "X-Original-Recipients: a@real.example" in sent.message().as_string()


def test_send_mail_is_covered_too(guarded):
    send_mail("Reset", "link", "from@example.test", ["user@real.example"])
    assert [m.to for m in mail.outbox] == [["qa@example.test"]]


def test_without_a_test_recipient_smtp_never_opens(guarded, no_smtp, caplog):
    guarded.NONPROD_TEST_RECIPIENT = ""
    guarded.EMAIL_BACKEND_INNER = SMTP
    assert send_mail("Reset", "link", "from@example.test", ["user@real.example"]) == 0
    with get_connection() as connection:  # opening is already outbound: refused too
        assert connection.send_messages([EmailMessage("x", "y", "f@e.test", ["u@r.e"])]) == 0
    assert no_smtp == []
    assert "core.mail.blocked_locally" in caplog.text


def test_the_smtp_test_proves_something_with_the_guard_patched_out(guarded, no_smtp, monkeypatch):
    guarded.NONPROD_TEST_RECIPIENT = ""
    guarded.EMAIL_BACKEND_INNER = SMTP
    monkeypatch.setattr(backends, "outbound_guard_active", lambda app_env: False)
    with pytest.raises(AssertionError, match="SMTP connection was opened"):
        send_mail("Reset", "link", "from@example.test", ["user@real.example"])
    assert len(no_smtp) == 1


def test_the_redirect_test_proves_something_with_the_guard_patched_out(guarded, monkeypatch):
    monkeypatch.setattr(backends, "outbound_guard_active", lambda app_env: False)
    send_mail("Reset", "link", "from@example.test", ["user@real.example"])
    assert mail.outbox[0].to == ["user@real.example"]  # the leak the redirect test catches


def test_a_log_only_backend_still_works_without_a_recipient(guarded):
    guarded.NONPROD_TEST_RECIPIENT = ""
    send_mail("Reset", "link", "from@example.test", ["user@real.example"])
    assert mail.outbox[0].to == ["user@real.example"]  # locmem: nothing leaves anyway


def test_production_passes_straight_through(guarded):
    guarded.APP_ENV = "production"
    send_mail("Reset", "link", "from@example.test", ["user@real.example"])
    assert (mail.outbox[0].to, mail.outbox[0].subject) == (["user@real.example"], "Reset")


@pytest.mark.parametrize(
    ("app_env", "wrapped"),
    [("production", False), ("development", True), ("staging", True), ("prod", True), ("", True)],
)
def test_settings_wrap_the_backend_everywhere_but_production(app_env, wrapped):
    assert outbound_guard_active(app_env) is wrapped


def test_e010_an_unguarded_delivering_backend_outside_production(settings):
    settings.APP_ENV = "staging"
    settings.EMAIL_BACKEND = SMTP
    assert [e.id for e in checks.check_outbound_guard(None)] == ["dbx.http.E010"]
    settings.EMAIL_BACKEND = LOCMEM  # never delivers: not a leak
    assert checks.check_outbound_guard(None) == []


def test_e011_a_delivering_inner_backend_with_nowhere_to_send(guarded):
    guarded.NONPROD_TEST_RECIPIENT = ""
    guarded.EMAIL_BACKEND_INNER = SMTP
    assert [e.id for e in checks.check_outbound_guard(None)] == ["dbx.http.E011"]
    guarded.NONPROD_TEST_RECIPIENT = "qa@example.test"
    assert checks.check_outbound_guard(None) == []


def test_production_has_no_guard_findings(settings):
    settings.APP_ENV = "production"
    settings.EMAIL_BACKEND = SMTP
    assert checks.check_outbound_guard(None) == []


def test_the_audit_judges_the_backend_that_would_deliver():
    ns = {"EMAIL_BACKEND": GUARDED_BACKEND, "EMAIL_BACKEND_INNER": SMTP, "EMAIL_HOST": "relay"}
    assert list(config_audit._email(ns)) == []
    ns["EMAIL_BACKEND_INNER"] = "django.core.mail.backends.console.EmailBackend"
    assert [f.code for f in config_audit._email(ns)] == ["cfg.E008"]
