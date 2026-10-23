"""
/api/core/activity/ (DATA_LIFECYCLE.md § 4.6): the read side of the audit trail. Read-only by
construction — a ReadOnlyModelViewSet's only verbs are GET, so every write verb answers 405 and
there is no permission that grants writing (a permission is something an administrator can widen).
Sorted by id, never created_at alone. The CSV export streams oldest-first and is itself audited.
"""

import csv
import io
import json
from datetime import UTC, datetime

from django.http import StreamingHttpResponse
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed

from core.api.viewsets import BaseViewSet
from core.audit import record
from core.models import ActivityLog
from core.serializers import ActivityLogSerializer

EXPORT_COLUMNS = (
    "id",
    "created_at",
    "channel",
    "action",
    "event",
    "description",
    "actor_label",
    "target_type",
    "target_id",
    "target_repr",
    "changes",
    "meta",
    "batch_id",
    "source",
    "origin_os_user",
    "origin_host",
    "origin_command",
    "request_id",
)
_INJECTION = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """CSV-injection escape (DOMAIN_PRIMITIVES § 6): a cell starting =, +, -, @ is a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_INJECTION) else text


def filtered(request):
    rows = ActivityLog.objects.all()
    params = request.query_params
    for name in ("channel", "action", "event", "source", "batch_id", "target_type", "target_id"):
        if params.get(name):
            rows = rows.filter(**{name: params[name]})
    if params.get("actor"):
        rows = rows.filter(actor_id=params["actor"])
    return rows


class ActivityLogViewSet(BaseViewSet, mixins.ListModelMixin):
    serializer_class = ActivityLogSerializer
    required_permissions = {"list": ["core.audit.view"], "export": ["core.audit.export"]}
    ordering_fields = ("id",)

    def initial(self, request, *args, **kwargs):
        # § 4.6: a write verb answers 405 to a signed-in caller. Without this the permission check
        # runs first and refuses with 403 — implying a permission exists that grants writing.
        # An ANONYMOUS caller still gets 401 from the normal chain: the route-enforcement
        # invariant (no route answers anonymous with anything but 401/403) holds for every verb.
        self.perform_authentication(request)
        signed_in = request.user and request.user.is_authenticated
        if signed_in and request.method.lower() not in self.action_map:
            raise MethodNotAllowed(request.method)
        super().initial(request, *args, **kwargs)

    def get_queryset(self):
        return filtered(self.request).order_by("-id")  # id is the sort key (§ 4.1)

    @action(detail=False, methods=["get"])
    def export(self, request):
        """Streamed over .iterator(), oldest-first. A human reading the evidence in bulk is itself
        an event, so the export is recorded BEFORE it streams."""
        record(
            "core.audit.exported",
            actor=request.user,
            meta={"filters": {k: v for k, v in request.query_params.items()}},
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

        def stream():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(EXPORT_COLUMNS)
            yield buffer.getvalue()
            for row in filtered(request).order_by("id").iterator(chunk_size=500):
                buffer.seek(0)
                buffer.truncate()
                writer.writerow(
                    csv_safe(
                        json.dumps(getattr(row, name), separators=(",", ":"))
                        if name in {"changes", "meta"}
                        else getattr(row, name)
                    )
                    for name in EXPORT_COLUMNS
                )
                yield buffer.getvalue()

        response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="audit-{stamp}.csv"'
        return response
