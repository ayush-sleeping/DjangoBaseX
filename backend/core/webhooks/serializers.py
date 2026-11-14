"""Shapes for /api/webhooks/. The signing secret is in NO serializer: the create and rotate views
add it to their one response, by hand, so a serializer that renders an endpoint cannot leak it."""

from rest_framework import serializers

from core.models import WebhookDelivery, WebhookEndpoint


class WebhookEndpointSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    events = serializers.SerializerMethodField()
    is_disabled_by_breaker = serializers.SerializerMethodField()

    class Meta:
        model = WebhookEndpoint
        fields = (
            "id",
            "name",
            "url",
            "events",
            "timeout_seconds",
            "custom_headers",
            "is_active",
            "is_disabled_by_breaker",
            "disabled_at",
            "consecutive_failures",
            "last_delivery_at",
            "previous_secret_expires_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_events(self, endpoint) -> list[str]:
        return sorted(s.event for s in endpoint.subscriptions.all())

    def get_is_disabled_by_breaker(self, endpoint) -> bool:
        return endpoint.disabled_at is not None


class WebhookEndpointWriteSerializer(serializers.Serializer):
    """Shape only: the service validates URL, events and headers (one owner of those rules)."""

    name = serializers.CharField(max_length=120)
    url = serializers.CharField(max_length=2048)
    events = serializers.ListField(child=serializers.CharField(max_length=100), allow_empty=True)
    timeout_seconds = serializers.IntegerField(required=False, allow_null=True)
    custom_headers = serializers.DictField(child=serializers.CharField(), required=False)
    is_active = serializers.BooleanField(required=False)


class WebhookDeliverySerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="delivery_id", read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = (
            "id",
            "event",
            "event_id",
            "status",
            "attempts",
            "next_attempt_at",
            "response_status",
            "response_body",
            "error_code",
            "duration_ms",
            "is_test",
            "payload",
            "created_at",
            "delivered_at",
            "failed_at",
        )
        read_only_fields = fields
