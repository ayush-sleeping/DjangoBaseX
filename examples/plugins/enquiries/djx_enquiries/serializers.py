"""Shape and validate only: no queries, no side effects (AGENTS.md § 3)."""

from rest_framework import serializers

from core.sdk import SOURCE_REF_PATTERN, allowed_transitions

from .models import Enquiry


class EnquirySerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = [
            "public_id",
            "number",
            "contact_name",
            "contact_email",
            "subject",
            "message",
            "status",
            "value",
            "allowed_transitions",
            "origin",
            "source_ref",
            "created_at",
        ]
        read_only_fields = fields

    def get_value(self, enquiry) -> dict[str, str]:
        return enquiry.value.as_json()

    def get_allowed_transitions(self, enquiry) -> list[str]:
        return allowed_transitions(enquiry, "status")  # the registry, no query


class EnquiryCreateSerializer(serializers.Serializer):
    contact_name = serializers.CharField(max_length=200)
    contact_email = serializers.EmailField()
    subject = serializers.CharField(max_length=200)
    message = serializers.CharField(required=False, allow_blank=True, default="")
    value_amount = serializers.DecimalField(max_digits=19, decimal_places=4)
    value_currency = serializers.CharField(min_length=3, max_length=3)
    source_ref = serializers.RegexField(SOURCE_REF_PATTERN, required=False)


class EnquiryUpdateSerializer(serializers.Serializer):
    contact_name = serializers.CharField(max_length=200, required=False)
    contact_email = serializers.EmailField(required=False)
    subject = serializers.CharField(max_length=200, required=False)
    message = serializers.CharField(required=False, allow_blank=True)
    value_amount = serializers.DecimalField(max_digits=19, decimal_places=4, required=False)
    value_currency = serializers.CharField(min_length=3, max_length=3, required=False)


class TransitionSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=Enquiry.Status.choices)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
