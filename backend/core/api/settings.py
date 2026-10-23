"""
/api/core/settings/ (CONFIGURATION.md § 9.8). Thin: parse, authorize, call core.settings_service,
respond. No create and no delete: a key exists because code declared it, and "reset" is its own
audited action.

    GET   /api/core/settings/?module=&group=   declarations + effective value + source + last change
    PATCH /api/core/settings/<key>/            {value, scope?, scope_id?, locked?, reason?}
    POST  /api/core/settings/<key>/reset/      {scope?, scope_id?, reason?}
"""

from rest_framework import status
from rest_framework.response import Response

from core import settings_service
from core.api.errors import from_exception, invalid_response
from core.api.views import BaseAPIView
from core.serializers import SettingResetSerializer, SettingSerializer, SettingWriteSerializer
from core.settings_registry import SettingError, SettingInvalid, UnknownSetting


def setting_error_response(exc: SettingError) -> Response:
    if isinstance(exc, UnknownSetting):
        return from_exception(exc, status.HTTP_404_NOT_FOUND)
    if isinstance(exc, SettingInvalid):
        return from_exception(
            exc, status.HTTP_400_BAD_REQUEST, details={"key": exc.key, "rule": exc.rule}
        )
    return from_exception(exc, status.HTTP_400_BAD_REQUEST)


class SettingListView(BaseAPIView):
    required_permissions = ["settings.settings.view"]

    def get(self, request):
        items = settings_service.describe(
            module=request.query_params.get("module") or None,
            group=request.query_params.get("group") or None,
        )
        return Response(SettingSerializer(items, many=True).data)


class SettingDetailView(BaseAPIView):
    required_permissions = ["settings.settings.manage"]

    def patch(self, request, key):
        serializer = SettingWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        data = serializer.validated_data
        try:
            settings_service.set_value(
                key,
                data["value"],
                scope=data["scope"],
                scope_id=data["scope_id"],
                locked=data["locked"],
                reason=data["reason"],
                actor=request.user,
            )
            item = settings_service.describe_one(key)
        except SettingError as exc:
            return setting_error_response(exc)
        return Response(SettingSerializer(item).data)


class SettingResetView(BaseAPIView):
    required_permissions = ["settings.settings.manage"]

    def post(self, request, key):
        serializer = SettingResetSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        data = serializer.validated_data
        try:
            settings_service.reset(
                key,
                scope=data["scope"],
                scope_id=data["scope_id"],
                reason=data["reason"],
                actor=request.user,
            )
            item = settings_service.describe_one(key)
        except SettingError as exc:
            return setting_error_response(exc)
        return Response(SettingSerializer(item).data)
