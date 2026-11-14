"""
manage.py backup (BUILD_ORDER 9.5; OPERATIONS.md § 9): a verified dump of the default database.

    manage.py backup                      label "manual", into <backend>/backups
    manage.py backup --label predeploy-1.4.0 --dir /var/backups/app

Prints only the path, size and checksum; never a connection URL or password. Exit codes: 0 ok,
2 configuration, 3 dump failed, 4 verification failed. The deploy driver treats any non-zero as
"do not migrate".
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from core.operations.backup import BackupError, create_backup, scrub


def migration_leaves() -> dict[str, str]:
    """The newest applied migration per app: restore compares it with the code's."""
    leaves: dict[str, str] = {}
    for app, name in (
        MigrationRecorder(connection).migration_qs.order_by("id").values_list("app", "name")
    ):
        leaves[app] = name
    return leaves


class Command(BaseCommand):
    help = "Dump the database, verify the dump, and record its state beside it."

    def add_arguments(self, parser):
        parser.add_argument("--label", default="manual")
        parser.add_argument("--dir", default=str(Path(settings.BASE_DIR) / "backups"))

    def handle(self, *args, label, dir, **options):
        db = dict(connection.settings_dict)
        try:
            result = create_backup(
                db,
                Path(dir),
                label,
                tables=len(connection.introspection.table_names()),
                source_env=str(settings.APP_ENV),
                version=str(getattr(settings, "APP_VERSION", "unknown")),
                migrations=migration_leaves(),
            )
        except BackupError as exc:
            raise CommandError(
                scrub(str(exc), str(db.get("PASSWORD") or "")), returncode=exc.code
            ) from None
        self.stdout.write(f"backup ok: {result.path} ({result.size} bytes, sha256 {result.sha256})")
