"""The webhook breaker notifies the people who can fix it (BUILD_ORDER 7.7; TECH_DEBT DB-81)."""

import pytest

pytestmark = pytest.mark.django_db


def test_a_tripped_webhook_endpoint_notifies_managers_and_re_enabling_resolves(
    django_capture_on_commit_callbacks, run_outbox, public_dns, make_endpoint
):
    from django.utils import timezone

    from core.models import Notification
    from core.webhooks import delivery
    from core.webhooks import service as webhooks
    from tests.core.webhooks.conftest import client_with

    manager = client_with("core.webhooks.manage").handler._force_user
    endpoint, _ = make_endpoint()
    threshold = webhooks.policy().breaker_threshold
    endpoint.consecutive_failures = threshold - 1
    endpoint.save()
    with django_capture_on_commit_callbacks(execute=True):
        delivery._count_failure(endpoint.pk, timezone.now())
    run_outbox()
    row = Notification.objects.get(recipient=manager, purpose_code="core.webhook_endpoint_disabled")
    assert row.resolved_at is None
    endpoint.refresh_from_db()
    assert endpoint.disabled_at is not None
    webhooks.update_endpoint(actor=manager, endpoint=endpoint, is_active=True)
    row.refresh_from_db()
    assert row.resolved_at is not None
