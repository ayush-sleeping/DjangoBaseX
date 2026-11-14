"""
The recycle bin (DATA_LIFECYCLE.md § 7.4). A soft-deletable model is registered with
register_recyclable(); the bin lists, restores and force-deletes by REGISTRY KEY only (an unknown
key is 404; a class name or "app.Model" from a request is never turned into a model). It is scoped
like everything else: rows come from all_objects.deleted() narrowed by visible_to / writable_by.
One permission, core.recycle_bin.manage, covers it; force-delete also needs the type's own delete
code. A retention policy purges rows binned longer than the window.
"""

from django.apps import apps
from django.db.models import ProtectedError, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response

from core.api.error_codes import ApiError
from core.api.views import BaseAPIView
from core.audit import log_activity
from core.querysets import VisibleToQuerySet
from core.registry import Recyclable, Registry, RegistryError, RetentionPolicy
from core.retention import register as register_retention

from .models import RestoreConflict, SoftDeleteModel, SoftDeleteQuerySet

PAGE = 100


def register_recyclable(registry: Registry, spec: Recyclable, *, days: int = 90) -> None:
    """Register the type and its purge policy `<owner>.recycle_bin_<name>` (floor 7 days, default
    `days`). Validates the model now (call from AppConfig.ready(), after models load)."""
    model = apps.get_model(spec.model)
    qs = model.all_objects.all() if hasattr(model, "all_objects") else None
    problems = []
    if not issubclass(model, SoftDeleteModel):
        problems.append("is not a SoftDeleteModel")
    if not isinstance(qs, SoftDeleteQuerySet) or not isinstance(qs, VisibleToQuerySet):
        problems.append("its queryset must be a SoftDeleteQuerySet and a VisibleToQuerySet")
    elif type(qs).visible_to is VisibleToQuerySet.visible_to:
        problems.append("its queryset does not implement visible_to()")
    try:
        model._meta.get_field(spec.title_field)
        model._meta.get_field("public_id")
    except Exception:  # noqa: BLE001 — FieldDoesNotExist: named below
        problems.append(f"needs fields {spec.title_field!r} and 'public_id'")
    if problems:
        raise RegistryError(f"recyclable {spec.key!r}: {'; '.join(problems)}")
    registry.recyclable.register(spec)
    owner, _, name = spec.key.partition(".")
    register_retention(
        registry,
        RetentionPolicy(
            key=f"{owner}.recycle_bin_{name.replace('-', '_')}",
            model=spec.model,
            timestamp_field="deleted_at",
            description=f"Deleted {spec.label.lower()} kept in the recycle bin before purging.",
            data_class="content",
            max_age_days=days,
            min_age_days=7,
            filter=Q(deleted_at__isnull=False),
        ),
    )


class BinRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    deleted_at = serializers.DateTimeField()
    deleted_by = serializers.CharField(allow_null=True)


class BinTypeSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class BinListSerializer(serializers.Serializer):
    type = serializers.CharField()
    results = BinRowSerializer(many=True)


class _BinView(BaseAPIView):
    required_permissions = ["core.recycle_bin.manage"]

    def spec(self, key: str) -> Recyclable:
        spec = self.registry.recyclable.get(key)
        if spec is None:
            raise ApiError("not_found")  # unknown, disabled and class-name keys all look alike
        return spec

    @property
    def registry(self):
        from core.registry import registry

        return registry

    def row(self, spec: Recyclable, public_id, *, queryset):
        model = apps.get_model(spec.model)
        obj = queryset(model.all_objects.deleted(), self.request.user).filter(public_id=public_id)
        row = obj.first()
        if row is None:
            raise ApiError("not_found")
        return model, row


class RecycleBinView(_BinView):
    @extend_schema(
        parameters=[OpenApiParameter("type", str)],
        responses={200: BinListSerializer},
    )
    def get(self, request):
        """Without ?type= the registered types; with it, that type's binned rows (newest first)."""
        key = request.query_params.get("type")
        if key is None:
            return Response(
                {
                    "types": BinTypeSerializer(
                        [
                            {"key": s.key, "label": s.label}
                            for s in self.registry.recyclable.enabled()
                        ],
                        many=True,
                    ).data
                }
            )
        spec = self.spec(key)
        model = apps.get_model(spec.model)
        rows = (
            model.all_objects.deleted()
            .visible_to(request.user)
            .select_related("deleted_by")
            .order_by("-deleted_at", "-pk")[:PAGE]
        )
        data = [
            {
                "id": r.public_id,
                "title": str(getattr(r, spec.title_field)),
                "deleted_at": r.deleted_at,
                "deleted_by": getattr(r.deleted_by, "email", None),
            }
            for r in rows
        ]
        return Response({"type": spec.key, "results": BinRowSerializer(data, many=True).data})


class RestoreView(_BinView):
    @extend_schema(request=None, responses={200: BinTypeSerializer})
    def post(self, request, type_key, public_id):
        spec = self.spec(type_key)
        _, obj = self.row(spec, public_id, queryset=lambda qs, user: qs.writable_by(user))
        try:
            obj.restore()
        except RestoreConflict as exc:
            raise ApiError("restore_conflict") from exc
        log_activity("core.recycle_bin.restored", actor=request.user, target=obj, type=spec.key)
        return Response({"key": spec.key, "label": spec.label})


class ForceDeleteView(_BinView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, type_key, public_id):
        spec = self.spec(type_key)
        if not request.user.has_perm(spec.delete_permission):
            raise ApiError("permission_denied")
        _, obj = self.row(spec, public_id, queryset=lambda qs, user: qs.writable_by(user))
        repr_, pk = str(obj), obj.pk
        try:
            obj.hard_delete()
        except ProtectedError as exc:
            blockers = sorted({o._meta.label for o in exc.protected_objects})
            raise ApiError("delete_blocked", details={"blocked_by": blockers}) from exc
        log_activity(
            "core.recycle_bin.force_deleted",
            actor=request.user,
            type=spec.key,
            id=str(pk),
            what=repr_,
        )
        return Response(status=204)
