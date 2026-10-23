"""
Re-encrypt every registered ciphertext under the newest key (JOBS § 25, BUILD 6.3).

    uv run python manage.py rotate_encryption [--purpose P] [--batch 500] [--dry-run]
    uv run python manage.py rotate_encryption --verify

The rotation procedure: prepend the new key → deploy → rotate_encryption → --verify shows zero rows
under the old key → remove it → deploy. Resumable by construction: a row already under the newest
key is skipped, so a run that died mid-way just runs again. One commit per batch — a crash loses at
most one batch of work, never the data (each row is rewritten, never cleared).

--verify counts rows per key fingerprint by trying each key (a Fernet token does not name its key).
A row no ring key decrypts is listed as UNREADABLE and left untouched: re-enter that secret or
restore its key.
"""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import crypto
from core.registry import registry


def registered_fields(purpose: str | None):
    fields = [f for f in registry.encrypted_fields.fields() if purpose in (None, f.purpose)]
    if purpose is not None and not fields:
        raise CommandError(f"no registered encrypted field has purpose {purpose!r}")
    return fields


class Command(BaseCommand):
    help = "Re-encrypt registered ciphertexts under the newest key, or --verify the keyring."

    def add_arguments(self, parser):
        parser.add_argument("--purpose", default=None)
        parser.add_argument("--batch", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--verify", action="store_true", help="count rows per key fingerprint")

    def handle(self, *args, purpose, batch, dry_run, verify, **options):
        try:
            newest = crypto.key_fingerprints()[0]
        except crypto.CryptoNotConfigured as exc:
            raise CommandError(str(exc)) from None
        if verify:
            return self.verify(purpose)
        for spec in registered_fields(purpose):
            self.rotate(spec, batch, dry_run, newest)

    def rotate(self, spec, batch_size: int, dry_run: bool, newest: str) -> None:
        model = apps.get_model(spec.model)
        rotated = skipped = unreadable = 0
        queryset = model.objects.exclude(**{spec.field: ""}).order_by("pk")
        pending: list = []
        for row in queryset.iterator(chunk_size=batch_size):
            token = getattr(row, spec.field)
            if crypto.fingerprint_of(token, purpose=spec.purpose) == newest:
                skipped += 1  # already the newest key: this is what makes a re-run resumable
                continue
            try:
                setattr(row, spec.field, crypto.rotate_token(token, purpose=spec.purpose))
            except crypto.DecryptionError:
                unreadable += 1  # left untouched; --verify lists it
                continue
            rotated += 1
            if not dry_run:
                pending.append(row)
                if len(pending) >= batch_size:
                    self.flush(model, spec.field, pending)
                    pending = []
        if pending:
            self.flush(model, spec.field, pending)
        did = "would rotate" if dry_run else "rotated"
        self.stdout.write(
            f"{spec.model}.{spec.field} [{spec.purpose}]: {did} {rotated}, "
            f"already newest {skipped}, unreadable {unreadable}"
        )
        if unreadable:
            raise CommandError(
                f"{unreadable} row(s) decrypt under no key in the ring. Nothing was lost — "
                "restore the missing key or re-enter those secrets, then re-run."
            )

    @staticmethod
    def flush(model, field: str, rows: list) -> None:
        with transaction.atomic():  # one commit per batch: a crash loses at most this batch's WORK
            model.objects.bulk_update(rows, [field])

    def verify(self, purpose: str | None) -> None:
        fingerprints = crypto.key_fingerprints()
        stale = False
        for spec in registered_fields(purpose):
            model = apps.get_model(spec.model)
            counts = dict.fromkeys([*fingerprints, crypto.UNREADABLE], 0)
            for row in model.objects.exclude(**{spec.field: ""}).iterator(chunk_size=500):
                owner = crypto.fingerprint_of(getattr(row, spec.field), purpose=spec.purpose)
                counts[owner or crypto.UNREADABLE] += 1
            summary = ", ".join(f"{fp}={n}" for fp, n in counts.items())
            self.stdout.write(f"{spec.model}.{spec.field} [{spec.purpose}]: {summary}")
            stale = stale or any(
                n for fp, n in counts.items() if fp != fingerprints[0] and fp != crypto.UNREADABLE
            )
            if counts[crypto.UNREADABLE]:
                stale = True
        if stale:
            raise CommandError(
                "rows remain under an older key (or unreadable): not yet safe to drop a key."
            )
        self.stdout.write("every row is under the newest key: safe to remove the older keys.")
