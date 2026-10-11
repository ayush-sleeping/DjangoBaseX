"""
Notes: the example plugin's one model (BUILD_ORDER 3.4).

Every table is notes_…, with Meta.db_table set explicitly (CORE_ARCHITECTURE_PLAN § 3). Rows are
reached only through Note.objects.visible_to(user), which fails closed (ADR-0011).
"""

import uuid

from django.conf import settings
from django.db import models

from core.querysets import VisibleToQuerySet


class NoteQuerySet(VisibleToQuerySet):
    def visible_to(self, user):
        """A person sees their own notes; a superuser sees all; anyone else, nothing."""
        if user is None or not user.is_authenticated:
            return self.none()
        if user.is_superuser:
            return self.all()
        return self.filter(owner=user)


class Note(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = NoteQuerySet.as_manager()

    class Meta:
        db_table = "notes_note"
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return self.title
