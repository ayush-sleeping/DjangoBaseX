"""
Uploads and private files (API_PLATFORM.md § 18–19).

An upload is judged by its BYTES, never by its name or the client's Content-Type: the magic number
must name a type the purpose allows, and the file's extension must agree with it, so `page.html`
renamed to `.png` is refused. Files are stored under MEDIA_ROOT/private with a generated name and
are never reachable by a public URL: the only way out is core.api.files.FileDownloadView, which
checks the purpose's read permission on every request.
"""

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage

from core.api.error_codes import ApiError

# type -> (leading bytes check, extensions). Deliberately small: a type is added with its purpose.
_EXTENSIONS = {
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/gif": (".gif",),
    "image/webp": (".webp",),
    "application/pdf": (".pdf",),
}
MAX_BYTES_DEFAULT = 5 * 1024 * 1024


def sniff(head: bytes) -> str | None:
    """The content type the leading bytes declare, or None for anything not on the list."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


@dataclass(frozen=True)
class FilePurpose:
    key: str
    read_permission: str  # checked on every download
    allowed_types: frozenset[str]
    max_bytes: int = MAX_BYTES_DEFAULT


PURPOSES: dict[str, FilePurpose] = {}


def register_purpose(purpose: FilePurpose) -> FilePurpose:
    if purpose.key in PURPOSES:
        raise ValueError(f"file purpose {purpose.key!r} is already registered")
    PURPOSES[purpose.key] = purpose
    return purpose


GENERAL = register_purpose(
    FilePurpose("general", "core.files.view", frozenset(_EXTENSIONS)),
)


def private_storage() -> FileSystemStorage:
    # base_url=None: the storage has no URL to hand out, by construction.
    return FileSystemStorage(location=Path(settings.MEDIA_ROOT) / "private", base_url=None)


def validate_upload(upload, purpose: FilePurpose) -> str:
    """Returns the sniffed content type, or raises ApiError('unsupported_file_type')."""
    if upload.size > purpose.max_bytes:
        raise ApiError(
            "unsupported_file_type", "The file is too large.", {"max": purpose.max_bytes}
        )
    head = upload.read(16)
    upload.seek(0)
    kind = sniff(head)
    extension = os.path.splitext(upload.name or "")[1].lower()
    if kind is None or kind not in purpose.allowed_types:
        raise ApiError("unsupported_file_type", "The file's contents are not an accepted type.")
    if extension not in _EXTENSIONS[kind]:
        raise ApiError(
            "unsupported_file_type", "The file's name does not match what the file contains."
        )
    return kind


def save_private(upload, purpose: FilePurpose, *, actor):
    from core.models import PrivateFile  # local: models import this package's siblings

    kind = validate_upload(upload, purpose)
    public_id = uuid.uuid4()
    stored = private_storage().save(f"{public_id}{_EXTENSIONS[kind][0]}", upload)
    return PrivateFile.objects.create(
        public_id=public_id,
        purpose=purpose.key,
        original_name=os.path.basename(upload.name or "")[:200],
        content_type=kind,
        size=upload.size,
        storage_name=stored,
        uploaded_by=actor,
    )
