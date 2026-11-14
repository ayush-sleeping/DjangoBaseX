"""
Business logic for notes (AGENTS.md § 3). Views call these and only these; every write runs in a
transaction and audits what it changed.
"""

from django.db import transaction

from core.sdk import log_activity, stamp_provenance

from .models import Note


def create_note(*, actor, title: str, body: str = "", source_ref: str | None = None) -> Note:
    with transaction.atomic():
        note = Note.objects.create(
            owner=actor,
            title=title,
            body=body,
            **stamp_provenance(actor=actor, source_ref=source_ref),
        )
    log_activity("notes.note.created", actor=actor, target=note)
    return note


def update_note(*, actor, note: Note, **changes) -> Note:
    with transaction.atomic():
        for name, value in changes.items():
            setattr(note, name, value)
        note.save(update_fields=[*changes, "updated_at"])
    log_activity("notes.note.updated", actor=actor, target=note, fields=sorted(changes))
    return note


def delete_note(*, actor, note: Note) -> None:
    """Bins the note (restorable from the recycle bin); it is purged by retention, not here."""
    with transaction.atomic():
        note.soft_delete(actor=actor)
    log_activity("notes.note.deleted", actor=actor, target=note)
