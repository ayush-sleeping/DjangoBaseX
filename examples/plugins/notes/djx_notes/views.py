"""
The plugin's API, mounted at /api/notes/ (registered in wiring.py; core names no plugin).

Thin: parse, authorize, delegate to services, respond (AGENTS.md § 3). Every action declares the
exact permission it enforces, and every read goes through Note.objects.visible_to().
"""

from rest_framework import mixins, status
from rest_framework.response import Response

from core.api.errors import invalid_response
from core.api.viewsets import BaseViewSet

from . import services
from .models import Note
from .serializers import NoteCreateSerializer, NoteSerializer


class NoteViewSet(BaseViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = NoteSerializer
    required_permissions = {
        "list": ["notes.notes.view"],
        "retrieve": ["notes.notes.view"],
        "create": ["notes.notes.create"],
        "destroy": ["notes.notes.delete"],
    }

    def get_queryset(self):
        return Note.objects.visible_to(self.request.user)

    def create(self, request):
        serializer = NoteCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid_response(serializer)
        note = services.create_note(actor=request.user, **serializer.validated_data)
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, public_id=None):
        services.delete_note(actor=request.user, note=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
