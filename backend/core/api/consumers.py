"""
/api/consumers/ — the admin API for machine callers (ADR-0016, API_PLATFORM.md § 8).
Thin: parse, authorize, call core.api_tokens.services (the only issuing path), respond. Human-only:
a token can never mint or revoke tokens. The plaintext token is in the issue and rotate responses
only, with Cache-Control: no-store.

    GET/POST         /api/consumers/
    GET/PATCH        /api/consumers/<id>/
    GET/POST         /api/consumers/<id>/tokens/
    PATCH            /api/consumers/<id>/tokens/<token_id>/       scopes
    POST             /api/consumers/<id>/tokens/<token_id>/rotate/
    POST             /api/consumers/<id>/tokens/<token_id>/revoke/
"""

from django.apps import apps
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api.errors import error_response, invalid_response
from core.api.viewsets import BaseViewSet
from core.api_tokens import services
from core.api_tokens.models import ApiConsumer, ApiToken


class ApiTokenSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    is_valid = serializers.SerializerMethodField()

    class Meta:
        model = ApiToken
        fields = (
            "id",
            "name",
            "prefix",
            "scopes",
            "expires_at",
            "last_used_at",
            "created_at",
            "revoked_at",
            "revoked_reason",
            "is_valid",
        )
        read_only_fields = fields

    def get_is_valid(self, obj) -> bool:
        from django.utils import timezone

        return obj.revoked_at is None and obj.expires_at > timezone.now()


class ApiTokenIssuedSerializer(ApiTokenSerializer):
    """The one response that carries the plaintext."""

    token = serializers.CharField(read_only=True)

    class Meta(ApiTokenSerializer.Meta):
        fields = (*ApiTokenSerializer.Meta.fields, "token")
        read_only_fields = fields


class ApiConsumerSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    service_role = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = ApiConsumer
        fields = (
            "id",
            "name",
            "description",
            "owner_team",
            "contact_email",
            "is_active",
            "service_role",
            "created_at",
            "disabled_at",
            "disabled_reason",
        )
        read_only_fields = fields


class ApiConsumerWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    owner_team = serializers.CharField(max_length=120, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    service_role = serializers.SlugField(max_length=64)
    is_active = serializers.BooleanField(required=False)
    disabled_reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ApiTokenIssueSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    scopes = serializers.ListField(child=serializers.CharField(max_length=128), allow_empty=False)
    expires_at = serializers.DateTimeField()


class ApiTokenScopesSerializer(serializers.Serializer):
    scopes = serializers.ListField(child=serializers.CharField(max_length=128), allow_empty=False)


class ApiTokenRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


def _token_error(exc: services.TokenError) -> Response:
    return error_response(
        "invalid", "Check the fields.", status.HTTP_400_BAD_REQUEST, {exc.field: [str(exc)]}
    )


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"
    return response


class ApiConsumerViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = ApiConsumerSerializer
    human_only = True  # tokens never administer tokens
    required_permissions = {
        "list": ["core.api_consumers.view"],
        "retrieve": ["core.api_consumers.view"],
        "tokens": ["core.api_consumers.view"],
        "create": ["core.api_consumers.manage"],
        "partial_update": ["core.api_consumers.manage"],
        "issue_token": ["core.api_tokens.issue"],
        "token_scopes": ["core.api_tokens.issue"],
        "rotate_token": ["core.api_tokens.issue"],
        "revoke_token": ["core.api_tokens.revoke"],
    }

    def get_queryset(self):
        return ApiConsumer.objects.select_related("service_role").order_by("name", "id")

    def _role(self, slug):
        return apps.get_model("rbac", "Role").objects.filter(slug=slug).first()

    @extend_schema(request=ApiConsumerWriteSerializer, responses={201: ApiConsumerSerializer})
    def create(self, request):
        serializer = ApiConsumerWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        data = dict(serializer.validated_data)
        role = self._role(data.pop("service_role"))
        if role is None:
            return error_response(
                "invalid", "Check the fields.", 400, {"service_role": ["No such role."]}
            )
        data.pop("disabled_reason", None)
        if ApiConsumer.objects.filter(name=data["name"]).exists():
            return error_response(
                "invalid", "Check the fields.", 400, {"name": ["This name is taken."]}
            )
        consumer = services.create_consumer(actor=request.user, service_role=role, **data)
        return Response(ApiConsumerSerializer(consumer).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=ApiConsumerWriteSerializer, responses=ApiConsumerSerializer)
    def partial_update(self, request, public_id=None):
        consumer = self.get_object()
        serializer = ApiConsumerWriteSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return invalid_response(serializer)
        data = dict(serializer.validated_data)
        if "service_role" in data:
            return error_response(
                "invalid",
                "Check the fields.",
                400,
                {"service_role": ["The service role cannot be changed; make a new consumer."]},
            )
        clash = ApiConsumer.objects.filter(name=data.get("name", consumer.name))
        if clash.exclude(pk=consumer.pk).exists():
            return error_response(
                "invalid", "Check the fields.", 400, {"name": ["This name is taken."]}
            )
        consumer = services.update_consumer(actor=request.user, consumer=consumer, **data)
        return Response(ApiConsumerSerializer(consumer).data)

    @extend_schema(responses=ApiTokenSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="tokens", url_name="tokens")
    def tokens(self, request, public_id=None):
        rows = self.get_object().tokens.order_by("-id")
        return Response(ApiTokenSerializer(rows, many=True).data)

    @extend_schema(request=ApiTokenIssueSerializer, responses={201: ApiTokenIssuedSerializer})
    @tokens.mapping.post
    def issue_token(self, request, public_id=None):
        consumer = self.get_object()
        serializer = ApiTokenIssueSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            token, plaintext = services.issue_token(
                actor=request.user, consumer=consumer, **serializer.validated_data
            )
        except services.TokenError as exc:
            return _token_error(exc)
        body = {**ApiTokenSerializer(token).data, "token": plaintext}
        return _no_store(Response(body, status=status.HTTP_201_CREATED))

    def _token(self, consumer, token_id) -> ApiToken:
        return get_object_or_404(ApiToken, consumer=consumer, public_id=token_id)

    @extend_schema(request=ApiTokenScopesSerializer, responses=ApiTokenSerializer)
    @action(detail=True, methods=["patch"], url_path=r"tokens/(?P<token_id>[0-9a-f-]{36})")
    def token_scopes(self, request, public_id=None, token_id=None):
        token = self._token(self.get_object(), token_id)
        serializer = ApiTokenScopesSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        try:
            token = services.set_scopes(
                actor=request.user, token=token, scopes=serializer.validated_data["scopes"]
            )
        except services.TokenError as exc:
            return _token_error(exc)
        return Response(ApiTokenSerializer(token).data)

    @extend_schema(request=None, responses={201: ApiTokenIssuedSerializer})
    @action(detail=True, methods=["post"], url_path=r"tokens/(?P<token_id>[0-9a-f-]{36})/rotate")
    def rotate_token(self, request, public_id=None, token_id=None):
        token = self._token(self.get_object(), token_id)
        try:
            successor, plaintext = services.rotate_token(actor=request.user, token=token)
        except services.TokenError as exc:
            return _token_error(exc)
        body = {**ApiTokenSerializer(successor).data, "token": plaintext}
        return _no_store(Response(body, status=status.HTTP_201_CREATED))

    @extend_schema(request=ApiTokenRevokeSerializer, responses=ApiTokenSerializer)
    @action(detail=True, methods=["post"], url_path=r"tokens/(?P<token_id>[0-9a-f-]{36})/revoke")
    def revoke_token(self, request, public_id=None, token_id=None):
        token = self._token(self.get_object(), token_id)
        serializer = ApiTokenRevokeSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        token = services.revoke_token(
            actor=request.user, token=token, reason=serializer.validated_data.get("reason", "")
        )
        return Response(ApiTokenSerializer(token).data)
