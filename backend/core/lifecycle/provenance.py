"""Provenance stamping (DATA_LIFECYCLE.md § 8): the one place `origin` and `created_via` are set."""

import re

from core import audit

from .models import SOURCE_REF_PATTERN

_SOURCE_REF = re.compile(SOURCE_REF_PATTERN)
# audit's provenance source → § 8's origin vocabulary (web · api · import · job · system)
_ORIGIN = {"web": "web", "command": "system", "system": "system"}


def stamp(*, actor=None, source_ref: str | None = None) -> dict:
    """
    Field values for a new row: {"created_via", "origin", "source_ref"}, to pass to create().
    A machine principal makes `api` rows tied to its consumer; anything else takes the write's
    ambient provenance. source_ref is validated here (a bad one is a ValueError, never stored).
    """
    if source_ref is not None and not _SOURCE_REF.match(source_ref):
        raise ValueError("source_ref has characters outside letters, digits and . _ : / # -")
    consumer = getattr(actor, "consumer", None) if getattr(actor, "is_machine", False) else None
    origin = "api" if consumer is not None else _ORIGIN.get(audit.provenance_source(), "system")
    return {"created_via": consumer, "origin": origin, "source_ref": source_ref}
