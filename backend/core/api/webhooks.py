"""
/api/webhooks/ (JOBS_AND_INTEGRATIONS.md § 16). Thin: parse, authorize, call core.webhooks.service,
respond. Platform-owned endpoints (no API-consumer model yet, BUILD_ORDER 9.2). The signing secret
appears in the create and rotate responses only.

    GET/POST   /api/webhooks/endpoints/
    GET/PATCH/DELETE /api/webhooks/endpoints/<id>/
    POST       /api/webhooks/endpoints/<id>/rotate-secret/
    POST       /api/webhooks/endpoints/<id>/send-test/
    GET        /api/webhooks/endpoints/<id>/deliveries/
    POST       /api/webhooks/endpoints/<id>/deliveries/<delivery_id>/redeliver/
    GET        /api/webhooks/events/            the catalogue
"""

from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api.errors import error_response, from_exception, invalid_response
from core.api.viewsets import BaseViewSet
from core.models import WebhookEndpoint
from core.registry import registry
from core.webhooks import service
from core.webhooks.serializers import (
    WebhookDeliverySerializer,
    WebhookEndpointSerializer,
    WebhookEndpointWriteSerializer,
)


def _invalid_field(exc: service.InvalidEndpoint) -> Response:
    return error_response(
        "invalid", "Check the fields.", status.HTTP_400_BAD_REQUEST, details={exc.field: [str(exc)]}
    )


class WebhookEndpointViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = WebhookEndpointSerializer
    required_permissions = {
        "list": ["core.webhooks.view"],
        "retrieve": ["core.webhooks.view"],
        "deliveries": ["core.webhooks.view"],
        "catalogue": ["core.webhooks.view"],
        "create": ["core.webhooks.manage"],
        "partial_update": ["core.webhooks.manage"],
        "destroy": ["core.webhooks.manage"],
        "rotate_secret": ["core.webhooks.manage"],
        "send_test": ["core.webhooks.manage"],
        "redeliver": ["core.webhooks.manage"],
    }

    def get_queryset(self):
        return WebhookEndpoint.objects.prefetch_related("subscriptions").order_by("-id")

    def _fresh(self, endpoint):
        return WebhookEndpointSerializer(self.get_queryset().get(pk=endpoint.pk)).data

    def create(self, request):
        serializer = WebhookEndpointWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            endpoint, secret = service.create_endpoint(
                actor=request.user, **serializer.validated_data
            )
        except service.InvalidEndpoint as exc:
            return _invalid_field(exc)
        return Response({**self._fresh(endpoint), "secret": secret}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, public_id=None):
        endpoint = self.get_object()
        serializer = WebhookEndpointWriteSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            service.update_endpoint(
                actor=request.user, endpoint=endpoint, **serializer.validated_data
            )
        except service.InvalidEndpoint as exc:
            return _invalid_field(exc)
        return Response(self._fresh(endpoint))

    def destroy(self, request, public_id=None):
        service.delete_endpoint(actor=request.user, endpoint=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, public_id=None):
        endpoint, secret = service.rotate_secret(actor=request.user, endpoint=self.get_object())
        return Response(
            {
                "secret": secret,
                "previous_secret_expires_at": endpoint.previous_secret_expires_at,
            }
        )

    @action(detail=True, methods=["post"], url_path="send-test")
    def send_test(self, request, public_id=None):
        delivery = service.send_test(actor=request.user, endpoint=self.get_object())
        return Response(WebhookDeliverySerializer(delivery).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def deliveries(self, request, public_id=None):
        rows = self.get_object().deliveries.order_by("-id")[: self.max_page_size]
        return Response(WebhookDeliverySerializer(rows, many=True).data)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"deliveries/(?P<delivery_id>[A-Za-z0-9_]+)/redeliver",
    )
    def redeliver(self, request, public_id=None, delivery_id=None):
        endpoint = self.get_object()
        delivery = endpoint.deliveries.filter(delivery_id=delivery_id).first()
        if delivery is None:
            return error_response("not_found", "No such delivery.", status.HTTP_404_NOT_FOUND)
        try:
            delivery = service.redeliver(actor=request.user, delivery=delivery)
        except service.NotRedeliverable as exc:
            return from_exception(exc, status.HTTP_409_CONFLICT)
        return Response(WebhookDeliverySerializer(delivery).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["get"])
    def catalogue(self, request):
        return Response(
            [
                {"event": e.name, "description": e.description, "object": e.object_type}
                for e in registry.events.external()
            ]
        )
