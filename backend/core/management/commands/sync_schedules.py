"""
Reconcile beat's schedule with the job registry (JOBS_AND_INTEGRATIONS.md § 6). Runs on every
migrate as well; this is the same sync by hand, and --dry-run prints the diff without writing.
"""

from django.core.management.base import BaseCommand

from core.jobs.schedules import sync_schedules


class Command(BaseCommand):
    help = (
        "Sync django-celery-beat's periodic tasks from the job registry. --dry-run writes nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print the diff; write nothing.")

    def handle(self, *args, dry_run, **options):
        report = sync_schedules(dry_run=dry_run)
        verb = "would " if dry_run else ""
        for action in ("created", "updated", "deleted"):
            for name in getattr(report, action):
                self.stdout.write(f"{verb}{action.rstrip('d')}{'' if dry_run else 'd'} {name}")
        for name in report.conflicts:
            self.stderr.write(
                self.style.ERROR(
                    f"conflict {name}: a PeriodicTask with this name exists and the registry does "
                    "not own it. Delete or rename it, then sync again."
                )
            )
        if not report.changed and not report.conflicts:
            self.stdout.write("schedules already match the registry")
