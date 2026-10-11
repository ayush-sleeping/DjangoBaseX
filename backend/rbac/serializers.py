"""Shapes for /api/rbac/ (AUTH_BLUEPRINT § 10.3). Validation only — writes go through services."""

from rest_framework import serializers

from .models import Permission, PermissionGroup, Role


class CatalogPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["code", "label", "is_deprecated"]


class CatalogGroupSerializer(serializers.ModelSerializer):
    permissions = CatalogPermissionSerializer(many=True, read_only=True)

    class Meta:
        model = PermissionGroup
        fields = ["code", "label", "module", "order", "permissions"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    user_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Role
        fields = [
            "public_id",
            "name",
            "slug",
            "description",
            "is_system",
            "is_elevated",
            "mfa_required",
            "permissions",
            "user_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_permissions(self, role) -> list[str]:
        return sorted(p.code for p in role.permissions.all())


class RoleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64)
    slug = serializers.SlugField(max_length=64)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    is_elevated = serializers.BooleanField(required=False, default=False)
    mfa_required = serializers.BooleanField(required=False, default=False)
    permissions = serializers.ListField(
        child=serializers.CharField(max_length=128), required=False, default=list
    )

    def validate_name(self, value):
        if Role.objects.filter(name=value).exists():
            raise serializers.ValidationError("A role with this name already exists.")
        return value

    def validate_slug(self, value):
        if Role.objects.filter(slug=value).exists():
            raise serializers.ValidationError("A role with this slug already exists.")
        return value


class RoleUpdateSerializer(serializers.Serializer):
    # The slug is what code refers to: immutable, so it is not accepted here.
    name = serializers.CharField(max_length=64, required=False)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    is_elevated = serializers.BooleanField(required=False)
    mfa_required = serializers.BooleanField(required=False)

    def validate_name(self, value):
        role = self.context["role"]
        if Role.objects.filter(name=value).exclude(pk=role.pk).exists():
            raise serializers.ValidationError("A role with this name already exists.")
        return value


class GrantsSerializer(serializers.Serializer):
    permissions = serializers.ListField(child=serializers.CharField(max_length=128))


class AssignRoleSerializer(serializers.Serializer):
    role = serializers.UUIDField()
