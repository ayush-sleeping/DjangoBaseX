"""
manage.py restore (BUILD_ORDER 9.5; OPERATIONS.md § 10): restore a verified dump, and come up safe.

    manage.py restore DUMP --yes                  restore; hold integrations if from another env
    manage.py restore --post-only --source-env production
                                                  the data is already restored by hand: run the hold
    manage.py restore --reenable SNAPSHOT.json    deliberately turn back on what the hold turned off

The source environment is read from DUMP's `.meta.json`, or given with --source-env; with neither
the command refuses (an unknown source is never assumed safe). When the source differs from this
install's APP_ENV, every schedule, webhook endpoint and outbound notification switch is turned OFF
(never deleted) and a config_snapshot is written beside the backups. A production-sourced dump into
a non-production target is refused without --allow-unsanitised: no sanitisers exist yet (TECH_DEBT).
Stop web, workers and beat before restoring, and start beat only after this command has finished.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.operations import restore as ops


class Command(BaseCommand):
    help = "Restore a verified dump; another environment's data comes up with integrations off."

    def add_arguments(self, parser):
        parser.add_argument("dump", nargs="?")
        parser.add_argument("--source-env", default=None)
        parser.add_argument("--post-only", action="store_true")
        parser.add_argument("--reenable", metavar="SNAPSHOT", default=None)
        parser.add_argument("--same-environment", action="store_true")
        parser.add_argument("--allow-unsanitised", action="store_true")
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--dir", default=str(Path(settings.BASE_DIR) / "backups"))

    def handle(self, *args, dump, source_env, post_only, reenable, same_environment, **options):
        if reenable:
            try:
                done = ops.reenable(Path(reenable))
            except ops.RestoreError as exc:
                raise CommandError(str(exc)) from None
            self.stdout.write(f"re-enabled: {done}")
            return
        target = str(settings.APP_ENV)
        path = Path(dump) if dump else None
        if post_only == bool(path):
            raise CommandError("give a DUMP to restore, or --post-only, not both and not neither")
        if path and not options["yes"]:
            raise CommandError("restore replaces the database: pass --yes after stopping the app")
        meta = ops.read_meta(path) if path else None
        source = source_env or (meta or {}).get("source_env")
        if not source and not same_environment:
            raise CommandError(
                "the dump's source environment is unknown: pass --source-env, or "
                "--same-environment if you are certain"
            )
        source = source or target
        other = ops.is_other_environment(source, target)
        if other and source.lower() == ops.PRODUCTION and not options["allow_unsanitised"]:
            raise CommandError(
                f"refusing a production dump into {target!r} without --allow-unsanitised "
                "(no sanitisers are registered yet)"
            )
        self.stdout.write(
            f"restore: source={source} target={target} hold={'yes' if other else 'no'}"
        )
        if path:
            try:
                connection.close()
                ops.restore_data(dict(connection.settings_dict), path)
            except ops.RestoreError as exc:
                raise CommandError(str(exc)) from None
        if not other:
            self.stdout.write("same environment: schedules and integrations left as restored")
            return
        snap, where = ops.hold(source, target, Path(options["dir"]))
        self.stdout.write(f"held (turned off, not deleted): {snap.counts()}")
        self.stdout.write(f"config_snapshot: {where}")
        self.stdout.write("re-enable deliberately: manage.py restore --reenable <that file>")
