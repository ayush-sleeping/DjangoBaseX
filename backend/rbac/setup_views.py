"""First-run setup endpoints (OPERATIONS.md § 3). Public only while setup is pending."""

from django.core.exceptions import ValidationError
from rest_framework import serializers, status
from rest_framework.response import Response

from core.api.errors import error_response, invalid_response
from core.api.views import BaseAPIView
from users.throttles import InvitationAcceptThrottle

from . import setup


class SetupCompleteSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200, write_only=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=256, write_only=True)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


class SetupStatusView(BaseAPIView):
    """GET: is first-run setup pending? A boolean, nothing else: it says nothing a login page
    does not."""

    public = True  # registry.public_routes
    authentication_classes: list = []
    throttle_classes = [InvitationAcceptThrottle]
    schema = None

    def get(self, request):
        return Response({"setup_required": setup.needed()})


class SetupCompleteView(BaseAPIView):
    """POST: create the first administrator. Answers 404 once setup is done (not 403: the endpoint
    is not an oracle for how the install was set up)."""

    public = True  # registry.public_routes
    authentication_classes: list = []
    throttle_classes = [InvitationAcceptThrottle]
    schema = None

    def post(self, request):
        if not setup.needed():
            return error_response("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        serializer = SetupCompleteSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        data = serializer.validated_data
        try:
            setup.complete(data["token"], data["email"], data["password"], data["full_name"])
        except setup.SetupSealed:
            return error_response("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        except setup.InvalidSetupToken:
            return error_response(
                "invalid_token", "That setup token is not valid.", status.HTTP_403_FORBIDDEN
            )
        except ValidationError as exc:
            return error_response(
                "invalid_input",
                "Choose a different email address or password.",
                status.HTTP_400_BAD_REQUEST,
                details=list(exc.messages),
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
