"""Shape and validate only: no queries, no side effects (AGENTS.md § 3)."""

from rest_framework import serializers

from core.sdk import SOURCE_REF_PATTERN

from .models import Note


class NoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Note
        fields = ["public_id", "title", "body", "origin", "source_ref", "created_at"]
        read_only_fields = fields


class NoteCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(required=False, allow_blank=True, default="")
    source_ref = serializers.RegexField(SOURCE_REF_PATTERN, required=False)  # the caller's own id


class NoteUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    body = serializers.CharField(required=False, allow_blank=True)
