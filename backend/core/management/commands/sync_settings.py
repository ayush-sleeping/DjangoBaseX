"""
Report what is wrong with the stored setting overrides (CONFIGURATION.md § 9.2, § 9.11).

    uv run python manage.py sync_settings

It never writes. Metadata lives in code, so there is nothing to sync into the database, and a
command with no write path cannot reset an admin's value however often it runs. Orphan rows (keys
no longer registered) are reported and kept. migrate runs the same report after every migration.

Exit status 1 when it finds a problem, so a deploy can choose to stop on one.
"""

from django.core.management.base import BaseCommand, CommandError

from core.registry import registry
from core.settings_service import report


class Command(BaseCommand):
    help = "Report stored setting overrides that are orphaned or no longer valid. Writes nothing."

    def handle(self, *args, **options):
        findings = report()
        declared = len(registry.settings.defs())
        if not findings:
            self.stdout.write(f"{declared} settings declared; every stored override is valid.")
            return
        for finding in findings:
            self.stdout.write(f"{finding.key} @ {finding.scope}: {finding.problem}")
        raise CommandError(f"{len(findings)} stored override(s) need attention (nothing changed).")
