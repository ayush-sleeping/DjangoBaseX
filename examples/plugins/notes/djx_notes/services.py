"""
Business logic for notes (AGENTS.md § 3). Views call these and only these; every write runs in a
transaction and audits what it changed.
"""

from django.db import transaction

from core.audit import log_activity

from .models import Note


def create_note(*, actor, title: str, body: str = "") -> Note:
    with transaction.atomic():
        note = Note.objects.create(owner=actor, title=title, body=body)
    log_activity("notes.note.created", actor=actor, target=note)
    return note


def delete_note(*, actor, note: Note) -> None:
    with transaction.atomic():
        note.delete()
    log_activity("notes.note.deleted", actor=actor, target=note)
