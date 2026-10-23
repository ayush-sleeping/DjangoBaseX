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


class FlagSerializer(serializers.Serializer):
    """One flag: the code declaration beside the stored state — and how long it has left."""

    def to_representation(self, item):
        defn, row = item["definition"], item["row"]
        return {
            "key": defn.key,
            "description": defn.description,
            "owner": defn.owner,
            "expires_on": defn.expires_on.isoformat(),
            "days_remaining": item["days_remaining"],
            "enabled": bool(row and row.enabled),
            "user_ids": list(row.user_ids or []) if row else [],
            "role_slugs": list(row.role_slugs or []) if row else [],
            "tenant_ids": list(row.tenant_ids or []) if row else [],
            "updated_at": row.updated_at.isoformat() if row else None,
        }


class FlagWriteSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    user_ids = serializers.ListField(child=serializers.CharField(), required=False)
    role_slugs = serializers.ListField(child=serializers.CharField(), required=False)
    tenant_ids = serializers.ListField(child=serializers.CharField(), required=False)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
