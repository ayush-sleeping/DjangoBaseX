"""
/api/core/lookups/ (CONFIGURATION.md § 14). GET is for any signed-in user — every select and
filter reads it. Writes go through core.lookups' one writer, behind settings.lookups.manage:
an admin adds or edits a value with no deploy, and the stable key is never writable.
"""

from rest_framework import status
from rest_framework.response import Response

from core import lookups
from core.api.errors import from_exception, invalid_response
from core.api.views import BaseAPIView
from core.models import LookupValue
from core.registry import registry
from core.serializers import LookupValueSerializer, LookupWriteSerializer


def lookup_error_response(exc: lookups.LookupError_) -> Response:
    if isinstance(exc, lookups.UnknownLookupSet):
        return from_exception(exc, status.HTTP_404_NOT_FOUND)
    return from_exception(exc, status.HTTP_400_BAD_REQUEST)


class LookupListView(BaseAPIView):
    required_permissions = []  # any signed-in user: selects and filters read this

    def get(self, request):
        set_key = request.query_params.get("set")
        if set_key and set_key not in registry.lookups:
            return lookup_error_response(lookups.UnknownLookupSet(set_key))
        rows = LookupValue.objects.all()
        if set_key:
            rows = rows.in_set(set_key)
        return Response(LookupValueSerializer(rows, many=True).data)


class LookupWriteView(BaseAPIView):
    required_permissions = ["settings.lookups.manage"]

    def post(self, request, set_key, key=None):
        """Add a value — the § 14 done-when: a new choice with no deploy."""
        if key is not None:  # POST creates under the collection; the value URL is PATCH's
            return self.http_method_not_allowed(request)
        return self._write(request, set_key, create=True, partial=False)

    def patch(self, request, set_key, key=None):
        if key is None:
            return self.http_method_not_allowed(request)
        return self._write(request, set_key, create=False, partial=True, key=key)

    def _write(self, request, set_key, *, create, partial, key=None):
        serializer = LookupWriteSerializer(data=request.data, partial=partial)
        if not serializer.is_valid():
            return invalid_response(serializer)
        data = dict(serializer.validated_data)
        key = key or data.pop("key", None)
        data.pop("key", None)  # the key is create-only; it is stable by design
        if not create and "is_active" in data and data["is_active"] is None:
            data.pop("is_active")
        try:
            row = lookups.set_lookup_value(
                set_key, key or "", actor=request.user, create=create, **data
            )
        except lookups.LookupError_ as exc:
            return lookup_error_response(exc)
        code = status.HTTP_201_CREATED if create else status.HTTP_200_OK
        return Response(LookupValueSerializer(row).data, status=code)
