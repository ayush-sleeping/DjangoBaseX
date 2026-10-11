from rest_framework import serializers

from core.registry import registry

from .models import User


class LoginSerializer(serializers.Serializer):
    # CharField, not EmailField: a malformed address must fail exactly like an unknown one.
    email = serializers.CharField(max_length=254, trim_whitespace=True)
    password = serializers.CharField(max_length=4096, trim_whitespace=False)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=254, trim_whitespace=True)


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)
    password = serializers.CharField(max_length=4096, trim_whitespace=False)


class PasswordConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=4096, trim_whitespace=False)


class MfaVerifySerializer(serializers.Serializer):
    mfa_token = serializers.CharField(max_length=2048)
    code = serializers.CharField(max_length=32)  # a 6-digit TOTP or a recovery code


class MfaConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)


class MeSerializer(serializers.ModelSerializer):
    # Effective permission codes arrive with RBAC (BUILD_ORDER 1.2); the shape is fixed now.
    permissions = serializers.SerializerMethodField()
    mfa_enabled = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "public_id",
            "email",
            "full_name",
            "is_staff",
            "is_superuser",
            "mfa_enabled",
            "mfa_enforced",
            "permissions",
        ]
        read_only_fields = fields

    def get_permissions(self, user) -> list[str]:
        # The effective codes, for the frontend's can(). A superuser holds the whole catalog.
        if user.is_superuser:
            return sorted(registry.permissions.codes())
        return sorted(user.get_all_permissions())

    def get_mfa_enabled(self, user) -> bool:
        return user.mfa_devices.filter(confirmed_at__isnull=False).exists()
