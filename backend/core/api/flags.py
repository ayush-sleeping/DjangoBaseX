"""
/api/core/flags/ (CONFIGURATION.md § 11). Thin: parse, authorize, call core.flags, respond.
The list is the ADMIN view of the whole catalogue (behind settings.flags.view); what a signed-in
user may see is only ever the on-for-me list on /api/auth/me/.
"""

from datetime import date

from rest_framework import status
from rest_framework.response import Response

from core import flags
from core.api.errors import from_exception, invalid_response
from core.api.views import BaseAPIView
from core.models import FeatureFlag
from core.registry import registry
from core.serializers import FlagSerializer, FlagWriteSerializer


def catalogue():
    rows = {row.key: row for row in FeatureFlag.objects.all()}
    return [
        {
            "definition": defn,
            "row": rows.get(defn.key),
            "days_remaining": (defn.expires_on - date.today()).days,
        }
        for defn in registry.flags.defs()
    ]


class FlagListView(BaseAPIView):
    required_permissions = ["settings.flags.view"]

    def get(self, request):
        return Response(FlagSerializer(catalogue(), many=True).data)


class FlagDetailView(BaseAPIView):
    required_permissions = ["settings.flags.manage"]

    def patch(self, request, key):
        serializer = FlagWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        changes = dict(serializer.validated_data)
        reason = changes.pop("reason")
        try:
            flags.set_flag(key, actor=request.user, reason=reason, **changes)
        except flags.UnknownFlag as exc:
            return from_exception(exc, status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return from_exception(
                type("Invalid", (Exception,), {"code": "invalid_value"})(str(exc)),
                status.HTTP_400_BAD_REQUEST,
            )
        item = next(i for i in catalogue() if i["definition"].key == key)
        return Response(FlagSerializer(item).data)
