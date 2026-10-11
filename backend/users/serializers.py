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


class RoleSummarySerializer(serializers.Serializer):
    # Read through the reverse relation; users never imports rbac's models (Ch. 2).
    public_id = serializers.UUIDField()
    slug = serializers.CharField()
    name = serializers.CharField()


class UserSerializer(serializers.ModelSerializer):
    mfa_enabled = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "public_id",
            "email",
            "full_name",
            "is_active",
            "is_superuser",
            "mfa_enabled",
            "last_login",
            "created_at",
            "deactivated_at",
            "deactivated_reason",
            "roles",
        ]
        read_only_fields = fields

    def get_mfa_enabled(self, user) -> bool:
        return any(d.confirmed_at for d in user.mfa_devices.all())

    def get_roles(self, user) -> list[dict]:
        return RoleSummarySerializer([ur.role for ur in user.user_roles.all()], many=True).data


class UserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class UserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, allow_blank=True)


class DeactivateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class InvitationSerializer(serializers.Serializer):
    public_id = serializers.UUIDField()
    email = serializers.EmailField()
    role = RoleSummarySerializer()
    invited_by = serializers.SerializerMethodField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField()
    accepted_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()

    def get_invited_by(self, invitation) -> dict | None:
        inviter = invitation.invited_by
        return {"public_id": inviter.public_id, "email": inviter.email} if inviter else None


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    role = serializers.UUIDField()


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)
    password = serializers.CharField(max_length=4096, trim_whitespace=False)
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
