"""
The plugin's API, mounted at /api/enquiries/ (registered in wiring.py; core names no plugin).

Thin: parse, authorize, delegate to services, respond (AGENTS.md § 3). Every action declares the
exact permission it enforces, and every read goes through Enquiry.objects.visible_to().
"""

from rest_framework import mixins, status
from rest_framework.response import Response

from core.sdk import (
    BaseViewSet,
    IllegalTransition,
    MoneyError,
    ReasonRequired,
    error_response,
    invalid_response,
)

from . import services
from .models import Enquiry
from .serializers import (
    EnquiryCreateSerializer,
    EnquirySerializer,
    EnquiryUpdateSerializer,
    TransitionSerializer,
)


def _money_refused(exc: MoneyError) -> Response:
    return error_response(
        "invalid",
        "Check the fields.",
        status.HTTP_400_BAD_REQUEST,
        details={"value_currency": [str(exc)]},
    )


class EnquiryViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = EnquirySerializer
    required_permissions = {
        "list": ["enquiries.enquiries.view"],
        "retrieve": ["enquiries.enquiries.view"],
        "create": ["enquiries.enquiries.create"],
        "partial_update": ["enquiries.enquiries.update"],
        "move": ["enquiries.enquiries.transition"],
        "destroy": ["enquiries.enquiries.delete"],
    }

    def get_queryset(self):
        return self.scope(Enquiry.objects)  # reads: visible_to, writes: writable_by (404 if unseen)

    def create(self, request):
        serializer = EnquiryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            enquiry = services.create_enquiry(actor=request.user, **serializer.validated_data)
        except MoneyError as exc:
            return _money_refused(exc)
        return Response(EnquirySerializer(enquiry).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, public_id=None):
        enquiry = self.get_object()
        serializer = EnquiryUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            enquiry = services.update_enquiry(
                actor=request.user, enquiry=enquiry, **serializer.validated_data
            )
        except MoneyError as exc:
            return _money_refused(exc)
        return Response(EnquirySerializer(enquiry).data)

    def move(self, request, public_id=None):
        enquiry = self.get_object()
        serializer = TransitionSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            services.move_enquiry(actor=request.user, enquiry=enquiry, **serializer.validated_data)
        except IllegalTransition as exc:
            return error_response(exc.code, str(exc), status.HTTP_409_CONFLICT)
        except ReasonRequired as exc:
            return error_response(
                exc.code, str(exc), status.HTTP_400_BAD_REQUEST, details={"reason": [str(exc)]}
            )
        return Response(EnquirySerializer(enquiry).data)

    def destroy(self, request, public_id=None):
        services.delete_enquiry(actor=request.user, enquiry=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
