"""
Documentation-only serializers for response bodies that are built as dicts (API_PLATFORM.md § 16).
They are never used to validate or render; drf-spectacular reads them so the OpenAPI contract
(and the frontend types generated from it) describe the real body instead of omitting the view.
"""

from rest_framework import serializers


class MfaChallengeSerializer(serializers.Serializer):
    mfa_required = serializers.BooleanField()
    mfa_token = serializers.CharField()


class RevokedCountSerializer(serializers.Serializer):
    revoked = serializers.IntegerField()


class MfaSetupSerializer(serializers.Serializer):
    otpauth_uri = serializers.CharField()
    secret = serializers.CharField()


class RecoveryCodesSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(child=serializers.CharField())


class NavigationSerializer(serializers.Serializer):
    sections = serializers.ListField(child=serializers.DictField())


class CryptoStatusSerializer(serializers.Serializer):
    configured = serializers.BooleanField()
    keys = serializers.ListField(child=serializers.DictField())
    fields = serializers.ListField(child=serializers.DictField())


class DynamicBodySerializer(serializers.Serializer):
    """A body assembled from registered contributors (bootstrap, public config): an object whose
    keys depend on what is installed, so the contract documents it as a free-form object."""
