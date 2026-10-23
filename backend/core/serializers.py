"""Shapes for /api/core/settings/ (CONFIGURATION.md § 9.8). Shape only; the service coerces."""

from rest_framework import serializers

from core.settings_registry import SCOPES


class SettingSerializer(serializers.Serializer):
    """One declaration as the settings screen needs it: what it is, what it is now, and why."""

    def to_representation(self, item):
        defn, resolved, row = item.definition, item.resolved, item.row
        changed_by = row.updated_by if row is not None else None
        return {
            "key": defn.key,
            "label": defn.label,
            "description": defn.description,
            "module": defn.module,
            "group": defn.group,
            **defn.type.describe(),
            "nullable": defn.nullable,
            "scopes": list(defn.scopes),
            "exposure": defn.exposure,
            "used_by": list(defn.used_by),
            "changed_by_event": defn.changed_by_event,
            "default": defn.to_json(defn.default),
            "value": defn.to_json(resolved.value),
            "source": resolved.source,
            "locked": resolved.locked,
            "updated_at": row.updated_at.isoformat() if row is not None else None,
            "updated_by": (
                {"public_id": str(changed_by.public_id), "email": changed_by.email}
                if changed_by is not None
                else None
            ),
        }


class SettingWriteSerializer(serializers.Serializer):
    value = serializers.JSONField(allow_null=True)  # null is the service's to accept or refuse
    scope = serializers.ChoiceField(choices=SCOPES, default="platform")
    scope_id = serializers.CharField(max_length=64, required=False, allow_null=True, default=None)
    locked = serializers.BooleanField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class SettingResetSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=SCOPES, default="platform")
    scope_id = serializers.CharField(max_length=64, required=False, allow_null=True, default=None)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
