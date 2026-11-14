"""notify(), the gate chain, preferences, the matrix, delivery semantics, email (7.7)."""

import pytest
from django.core import mail
from django.core.exceptions import ValidationError  # noqa: F401
from django.db import transaction

from core import checks, settings_service
from core.mail import render
from core.models import (
    NotificationDelivery,
    NotificationPreference,
    NotificationPurposeState,
    NotificationSetting,
)
from core.notifications import channels, engine, service
from core.notifications.api import NotifyError, notify
from core.registry import registry
from tests.core.notifications.conftest import CONTEXT
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def last(code):
    return NotificationDelivery.objects.filter(purpose_code=code).order_by("-id")


def route(code="tests.broadcast", addresses=("ops@example.com",)):
    return service.save_route(
        actor=None, purpose_code=code, channel="email", target={"addresses": list(addresses)}
    )


# --- done-when: no destination in code; a failing channel never fails the save -------------------


def test_a_caller_can_notify_with_no_destination_in_code(purposes, fire):
    route(addresses=("ops@example.com", "oncall@example.com"))
    fire("tests.broadcast", context=CONTEXT)
    assert sorted(m.to[0] for m in mail.outbox) == ["oncall@example.com", "ops@example.com"]


def test_notify_refuses_an_address_as_a_recipient(purposes):
    with pytest.raises(NotifyError):
        notify("tests.plain", recipients=["someone@example.com"])
    with pytest.raises(NotifyError):
        notify("tests.nope")


def test_a_failing_channel_never_fails_the_save(
    purposes, user, monkeypatch, django_capture_on_commit_callbacks, run_outbox
):
    def explode(self, message):
        raise RuntimeError("provider down")

    monkeypatch.setattr(channels.EmailChannel, "send", explode)
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            saved = UserFactory()
            notify("tests.plain", recipients=[user], context=CONTEXT)
    run_outbox()
    assert type(saved).objects.filter(pk=saved.pk).exists()  # the business change committed
    row = last("tests.plain").get(channel="email")
    assert row.status == "unknown" and row.error_code == "adapter_error"


def test_an_enqueue_failure_does_not_raise_into_the_save(
    purposes, user, monkeypatch, django_capture_on_commit_callbacks
):
    from core.notifications import api

    monkeypatch.setattr(api, "enqueue", lambda *a, **k: 1 / 0)
    with django_capture_on_commit_callbacks(execute=True):
        notify("tests.plain", recipients=[user], context=CONTEXT)


def test_notify_inside_a_rolled_back_transaction_sends_nothing(
    purposes, user, django_capture_on_commit_callbacks, run_outbox
):
    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                notify("tests.plain", recipients=[user], context=CONTEXT)
                raise RuntimeError("business failure")
        except RuntimeError:
            pass
    run_outbox()
    assert not mail.outbox and not NotificationDelivery.objects.exists()


# --- the gate chain: every stop says why ----------------------------------------------------------


def test_platform_switch_stops_everything(purposes, user, fire):
    settings_service.set_value("notifications.delivery.enabled", False)
    fire("tests.plain", recipients=[user], context=CONTEXT)
    assert not mail.outbox and not NotificationDelivery.objects.exists()


def test_matrix_off_stops_a_channel(purposes, user, fire):
    NotificationSetting.objects.create(purpose_code="tests.plain", channel="email", enabled=False)
    fire("tests.plain", recipients=[user], context=CONTEXT)
    assert not mail.outbox
    assert list(last("tests.plain").values_list("channel", flat=True)) == ["in_app"]


def test_no_route_and_no_recipient_are_logged_stops(purposes, fire):
    fire("tests.broadcast", context=CONTEXT)  # a broadcast purpose with no route
    fire("tests.plain", recipients=[], context=CONTEXT)  # nobody resolved
    assert not mail.outbox and not NotificationDelivery.objects.exists()


def test_each_row_level_gate_records_its_skip_reason(purposes, user, fire, no_test_routing):
    no_test_routing("tests.plain")
    gone = UserFactory(is_active=False)
    NotificationPreference.objects.create(
        user=user, purpose_code="tests.plain", channel="email", enabled=False
    )
    fire("tests.plain", recipients=[user, gone], context=CONTEXT)
    reasons = {(r.recipient_id, r.channel): r.skip_reason for r in last("tests.plain")}
    assert reasons[(user.pk, "email")] == "opted_out"
    assert reasons[(gone.pk, "email")] == "recipient_inactive"
    assert reasons[(user.pk, "in_app")] == ""  # the in_app channel is not opted out
    fire("tests.plain", recipients=[user], context=CONTEXT, dedupe_key="period-1")
    fire("tests.plain", recipients=[user], context=CONTEXT, dedupe_key="period-1")
    assert last("tests.plain").filter(skip_reason="duplicate", channel="in_app").exists()


def test_reminder_dedupe_fails_closed_when_the_check_errors(purposes, user, monkeypatch, fire):
    real = NotificationDelivery.objects.create

    def broken(**fields):
        raise RuntimeError("database trouble")

    monkeypatch.setattr(NotificationDelivery.objects, "create", broken)
    fire("tests.plain", recipients=[user], context=CONTEXT, dedupe_key="period-1")
    monkeypatch.setattr(NotificationDelivery.objects, "create", real)
    assert not mail.outbox and not NotificationDelivery.objects.exists()


# --- preferences ---------------------------------------------------------------------------------


def test_preferences_resolve_user_then_system_then_code_default(purposes, user):
    plain = purposes["tests.plain"]
    assert engine.preference_enabled(user.pk, plain, "email") is True  # code default
    NotificationPreference.objects.create(
        user=None, purpose_code="tests.plain", channel="email", enabled=False
    )
    assert engine.preference_enabled(user.pk, plain, "email") is False  # the system default row
    NotificationPreference.objects.create(
        user=user, purpose_code="tests.plain", channel="email", enabled=True
    )
    assert engine.preference_enabled(user.pk, plain, "email") is True  # the user's own row wins


def test_only_one_system_default_row_per_cell(db):
    from django.db import IntegrityError

    make = lambda: NotificationPreference.objects.create(  # noqa: E731
        user=None, purpose_code="tests.plain", channel="email", enabled=False
    )
    make()
    with pytest.raises(IntegrityError), transaction.atomic():
        make()


def test_a_security_purpose_cannot_be_opted_out(purposes, user, fire, no_test_routing):
    no_test_routing("tests.security")
    with pytest.raises(service.Locked):
        service.set_preferences(
            user=user, changes=[{"purpose": "tests.security", "channel": "email", "enabled": False}]
        )
    with pytest.raises(service.Locked):
        service.set_cells(
            actor=None,
            changes=[{"purpose": "tests.security", "channel": "email", "enabled": False}],
        )
    # even a row that got there another way is ignored at dispatch
    NotificationPreference.objects.create(
        user=user, purpose_code="tests.security", channel="email", enabled=False
    )
    NotificationSetting.objects.create(
        purpose_code="tests.security", channel="email", enabled=False
    )
    fire("tests.security", recipients=[user], context=CONTEXT)
    assert len(mail.outbox) == 1


# --- the matrix ----------------------------------------------------------------------------------


def test_sync_seeds_from_code_and_never_overwrites_an_admin_choice(purposes):
    engine.sync_matrix()
    cell = NotificationSetting.objects.get(purpose_code="tests.plain", channel="email")
    assert cell.enabled is True
    NotificationSetting.objects.filter(pk=cell.pk).update(enabled=False)
    NotificationPurposeState.objects.filter(purpose_code="tests.rollout").update(test_routing=False)
    engine.sync_matrix()
    assert NotificationSetting.objects.get(pk=cell.pk).enabled is False
    assert NotificationPurposeState.objects.get(purpose_code="tests.rollout").test_routing is False


def test_a_removed_purpose_has_its_rows_deleted(purposes, monkeypatch):
    engine.sync_matrix()
    monkeypatch.delitem(registry.notification_purposes._purposes, "tests.plain")
    engine.sync_matrix()
    assert not NotificationSetting.objects.filter(purpose_code="tests.plain").exists()
    assert NotificationSetting.objects.filter(purpose_code="tests.broadcast").exists()


# --- test routing and send test ------------------------------------------------------------------


def test_rollout_purposes_default_to_test_routing_and_name_the_intended_recipients(
    purposes, user, fire
):
    settings_service.set_value("notifications.delivery.test_recipient", "tester@example.com")
    fire("tests.rollout", recipients=[user], context=CONTEXT)
    sent = [m for m in mail.outbox if m.to != [user.email]]
    assert [m.to for m in mail.outbox] == [["tester@example.com"]]
    assert user.email in sent[0].body and sent[0].subject.startswith("[TEST ROUTED]")


def test_test_routing_without_a_tester_holds_the_mail(purposes, user, fire):
    fire("tests.rollout", recipients=[user], context=CONTEXT)
    assert not mail.outbox
    assert last("tests.rollout").filter(skip_reason="test_routing_no_tester").exists()


def test_token_bearing_purpose_is_never_test_routed_in_production(purposes, user, settings, fire):
    settings.APP_ENV = "production"
    settings_service.set_value("notifications.delivery.test_recipient", "tester@example.com")
    fire(
        "tests.tokenrollout",
        recipients=[user],
        context={"link_path": "reset-password", "token": "abc", "minutes": 5},
    )
    assert [m.to for m in mail.outbox] == [[user.email]]  # the real recipient, not the tester
    with pytest.raises(service.Locked):
        service.set_cells(
            actor=None, changes=[{"purpose": "tests.tokenrollout", "test_routing": True}]
        )
    settings.APP_ENV = "test"
    assert engine.test_routing_on(purposes["tests.tokenrollout"]) is True  # non-prod: redirected


def all_purposes():
    from users.notifications import PURPOSES  # noqa: F401 — ensures registration imports

    return [p.code for p in registry.notification_purposes.purposes()]


@pytest.mark.parametrize("code", all_purposes())
def test_send_test_works_for_every_purpose_and_route(code, user, purposes):
    purpose = registry.notification_purposes.get(code)
    results = service.send_test(actor=user, purpose_code=code)
    assert results and all(r["status"] == "sent" for r in results), results
    if "broadcast" in purpose.audience:
        saved = route(code, addresses=("ops@example.com",))
        via_route = service.send_test(actor=user, purpose_code=code, route=saved)
        assert via_route and all(r["status"] == "sent" for r in via_route), via_route
        assert "ops@example.com" in [m.to[0] for m in mail.outbox]
    assert all(m.subject.startswith("[TEST]") for m in mail.outbox)


def test_send_test_goes_through_the_real_adapter(user, purposes, monkeypatch):
    seen = []
    monkeypatch.setattr(
        channels.EmailChannel,
        "send",
        lambda self, m: seen.append(m) or channels.DeliveryResult.accepted(),
    )
    service.send_test(actor=user, purpose_code="tests.plain", channel="email")
    assert len(seen) == 1 and seen[0].subject.startswith("[TEST]")


# --- delivery semantics --------------------------------------------------------------------------


def test_an_ambiguous_send_is_unknown_and_never_resent(
    purposes, user, monkeypatch, fire, run_outbox
):
    calls = []

    def ambiguous(self, message):
        calls.append(message)
        return channels.DeliveryResult.unknown("timeout")

    monkeypatch.setattr(channels.EmailChannel, "send", ambiguous)
    fire("tests.plain", recipients=[user], context=CONTEXT)
    run_outbox()
    run_outbox()
    assert len(calls) == 1
    assert last("tests.plain").get(channel="email").status == "unknown"


def test_a_stale_unknown_row_is_not_resent(purposes, user, monkeypatch):
    row = NotificationDelivery.objects.create(
        purpose_code="tests.plain", channel="email", recipient=user, target_hash="x",
        status="unknown",
    )  # fmt: skip
    called = []
    monkeypatch.setattr(channels.EmailChannel, "send", lambda s, m: called.append(m))
    assert engine.send_delivery(row).code == "already_attempted"
    assert not called


def test_provider_error_detail_is_not_stored(purposes, user, monkeypatch, fire):
    monkeypatch.setattr(
        channels.EmailChannel,
        "send",
        lambda s, m: channels.DeliveryResult.unknown("smtp: 550 to=a@b.c"),
    )
    fire("tests.plain", recipients=[user], context=CONTEXT)
    row = last("tests.plain").get(channel="email")
    assert row.provider_ref == "" and not row.context.get("token")


def test_a_token_is_never_written_to_a_table(user, fire, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        notify(
            "users.password_reset",
            recipients=[user],
            context={"link_path": "reset-password", "token": "SECRET-TOKEN", "minutes": 5},
        )
    assert "SECRET-TOKEN" in mail.outbox[0].body
    from core.models import OutboxMessage

    stored = [str(r.payload) for r in OutboxMessage.objects.all()]
    stored += [str(r.context) for r in NotificationDelivery.objects.all()]
    assert not any("SECRET-TOKEN" in s for s in stored)


# --- email ---------------------------------------------------------------------------------------


def test_subject_newlines_are_stripped_and_not_autoescaped():
    subject, _, html = render.render_email(
        "core/email/webhook_endpoint_disabled",
        {"endpoint_name": "A\r\nBcc: x & <b>", "failures": 1},
    )
    assert "\n" not in subject and "\r" not in subject
    assert "& <b>" in subject  # autoescape off in the subject
    assert "&amp;" in html and "<b>" not in html  # autoescape on in the body


def test_links_use_frontend_base_url_never_the_host_header(
    settings, client, django_capture_on_commit_callbacks
):
    settings.FRONTEND_BASE_URL = "https://app.example.test"
    settings.ALLOWED_HOSTS = ["*"]  # the Host header is accepted: the link must still ignore it
    user = UserFactory()
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            "/api/auth/password/forgot/",
            {"email": user.email},
            content_type="application/json",
            HTTP_HOST="evil.example",
        )
    assert response.status_code == 204
    assert "https://app.example.test/reset-password?token=" in mail.outbox[0].body
    assert "evil.example" not in mail.outbox[0].body


def test_send_email_returns_false_and_never_raises(settings, monkeypatch):
    monkeypatch.setattr(
        render.EmailMultiAlternatives,
        "send",
        lambda self, **kw: (_ for _ in ()).throw(OSError("x")),
    )
    assert (
        render.send_email("core/email/webhook_endpoint_disabled", "a@example.com", CONTEXT) is False
    )
    assert render.send_email("core/email/does_not_exist", "a@example.com", {}) is False
    assert (
        render.send_email("core/email/webhook_endpoint_disabled", ["a@example.com"] * 99, CONTEXT)
        is False
    )


def test_production_refuses_a_log_only_email_backend(settings):
    settings.APP_ENV = "production"
    settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    assert [e.id for e in checks.check_email_backend_in_production(None)] == ["dbx.notify.E010"]
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    assert checks.check_email_backend_in_production(None) == []
    settings.APP_ENV = "staging"
    settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    assert checks.check_email_backend_in_production(None) == []


def test_every_purpose_preview_renders_for_every_default_channel(user):
    codes = all_purposes()
    assert codes, "an empty registry would make this test pass for nothing"
    for purpose in registry.notification_purposes.purposes():
        context = engine.sample_context(purpose)
        for key in purpose.default_channels:
            message = engine.adapter(key).render(
                purpose, context, recipient=user, address=user.email
            )
            assert not isinstance(message, channels.DeliveryResult), (purpose.code, key, message)
