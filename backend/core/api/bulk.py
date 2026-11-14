"""
Bulk actions on a BaseViewSet (DOMAIN_PRIMITIVES.md § 5).

    POST /<resource>/bulk/<action>/
      {"ids": ["<public id>", ...]}
      {"all_matching": true, "filters": {<the list's own query params>}, "exclude_ids": [...],
       "expected_count": 42}

Both forms resolve their rows through the SAME code the list endpoint runs: get_queryset() under
the READ scope (visible_to), then run_list() with those params. "All matching" therefore touches
exactly the rows the list shows for the same filters, never a looser set. A row the caller can read
but not write is skipped (`not_writable`), not acted on and not rejected wholesale.

A request over MAX_SYNC_ROWS is refused (400 bulk_too_large); running such an action as a job is
deferred (TECH_DEBT DB-130).
"""

import logging
import uuid
from typing import ClassVar

from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from core import audit
from core.api.error_codes import ApiError
from core.registry import registry

logger = logging.getLogger("core.bulk")

MAX_SYNC_ROWS = 500


class Skip(Exception):
    """Raised by a bulk handler for a protected row: it is reported, the batch carries on."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code, self.message = code, message or code


class BulkRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.CharField(), required=False)
    all_matching = serializers.BooleanField(required=False, default=False)
    filters = serializers.DictField(child=serializers.CharField(), required=False)
    exclude_ids = serializers.ListField(child=serializers.CharField(), required=False)
    expected_count = serializers.IntegerField(required=False, min_value=0)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate(self, attrs):
        if bool(attrs.get("ids")) == bool(attrs.get("all_matching")):
            raise serializers.ValidationError(
                "Send either ids or all_matching, not both or neither."
            )
        if attrs.get("filters") and not attrs.get("all_matching"):
            raise serializers.ValidationError({"filters": "filters only apply with all_matching."})
        return attrs


class BulkSkipSerializer(serializers.Serializer):
    id = serializers.CharField()
    code = serializers.CharField()
    message = serializers.CharField()


class BulkResultSerializer(serializers.Serializer):
    requested = serializers.IntegerField()
    affected = serializers.IntegerField()
    skipped = serializers.IntegerField()
    skipped_reasons = BulkSkipSerializer(many=True)
    batch_id = serializers.UUIDField()
    job_id = serializers.CharField(allow_null=True)


class BulkActionsMixin:
    """Put before BaseViewSet. Set `bulk_resource` ("users.user") and allow the `bulk` action in
    required_permissions with [] (the registered action's own permission is enforced below)."""

    bulk_resource: ClassVar[str] = ""

    def _matching(self, body: dict):
        """The read-scoped, list-filtered queryset: the list endpoint's own pipeline."""
        self._scope_as_read = True
        self._list_params = body.get("filters") or {} if body.get("all_matching") else {}
        try:
            queryset = self.filter_queryset(self.get_queryset())
        finally:
            self._scope_as_read = False
            self._list_params = None
        return queryset

    @action(
        detail=False,
        methods=["post"],
        url_path=r"bulk/(?P<bulk_name>[a-z][a-z0-9_]*)",
    )
    def bulk(self, request, bulk_name=None):
        spec = registry.bulk_actions.get(self.bulk_resource, bulk_name or "")
        if spec is None:
            raise ApiError("not_found")
        if not request.user.has_perm(spec.permission):
            raise ApiError("permission_denied")
        serializer = BulkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = serializer.validated_data
        lookup = self.lookup_field

        queryset = self._matching(body)
        if body.get("all_matching"):
            matching = list(queryset.values_list(lookup, flat=True))
            excluded = {str(i) for i in body.get("exclude_ids", ())}
            ids = [str(i) for i in matching if str(i) not in excluded]
            expected = body.get("expected_count")
            if expected is not None and expected != len(ids):
                raise ApiError("bulk_selection_changed", details={"count": len(ids)})
            requested = len(ids)
            unseen: list[str] = []
        else:
            asked = list(dict.fromkeys(str(i) for i in body["ids"]))
            visible = {
                str(i)
                for i in queryset.filter(**{f"{lookup}__in": asked}).values_list(lookup, flat=True)
            }
            ids = [i for i in asked if i in visible]
            unseen = [i for i in asked if i not in visible]
            requested = len(asked)
        if requested > MAX_SYNC_ROWS:
            raise ApiError("bulk_too_large", details={"max": MAX_SYNC_ROWS, "requested": requested})

        writable = {
            str(i)
            for i in queryset.writable_by(request.user)
            .filter(**{f"{lookup}__in": ids})
            .values_list(lookup, flat=True)
        }
        skipped = [{"id": i, "code": "not_found", "message": "No such row."} for i in unseen] + [
            {"id": i, "code": "not_writable", "message": "You may not change this row."}
            for i in ids
            if i not in writable
        ]
        todo = [i for i in ids if i in writable]

        batch_id = uuid.uuid4()
        affected = 0
        model = queryset.model
        with audit.batch(batch_id):
            for start in range(0, len(todo), spec.batch_size):
                chunk = todo[start : start + spec.batch_size]
                rows = {
                    str(getattr(o, lookup)): o
                    for o in model._default_manager.filter(**{f"{lookup}__in": chunk})
                }
                for row_id in chunk:
                    obj = rows.get(row_id)
                    if obj is None:  # deleted between resolving and acting
                        skipped.append({"id": row_id, "code": "gone", "message": "Row is gone."})
                        continue
                    try:
                        with transaction.atomic():
                            spec.handler(actor=request.user, obj=obj, reason=body.get("reason", ""))
                        affected += 1
                    except Skip as skip:
                        skipped.append({"id": row_id, "code": skip.code, "message": skip.message})
                    except Exception:  # one bad row must not abort the other 199
                        logger.exception("bulk %s failed on %s", spec.key, row_id)
                        skipped.append(
                            {"id": row_id, "code": "failed", "message": "Could not be changed."}
                        )
            audit.log_activity(
                "core.bulk.completed",
                actor=request.user,
                action=spec.key,
                requested=requested,
                affected=affected,
                skipped=len(skipped),
                batch_id=str(batch_id),
            )
        return Response(
            {
                "requested": requested,
                "affected": affected,
                "skipped": len(skipped),
                "skipped_reasons": skipped,
                "batch_id": batch_id,
                "job_id": None,
            }
        )
