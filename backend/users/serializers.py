from rest_framework import serializers

from .models import User


class LoginSerializer(serializers.Serializer):
    # CharField, not EmailField: a malformed address must fail exactly like an unknown one.
    email = serializers.CharField(max_length=254, trim_whitespace=True)
    password = serializers.CharField(max_length=4096, trim_whitespace=False)


class MeSerializer(serializers.ModelSerializer):
    # Effective permission codes arrive with RBAC (BUILD_ORDER 1.2); the shape is fixed now.
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["public_id", "email", "full_name", "is_staff", "is_superuser", "permissions"]
        read_only_fields = fields

    def get_permissions(self, user) -> list[str]:
        return []
