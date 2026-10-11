from django.core.management.base import BaseCommand

from rbac.seeding import sync_catalog


class Command(BaseCommand):
    help = "Project the code permission catalog onto the database. Idempotent; never deletes."

    def handle(self, *args, **options):
        report = sync_catalog()
        for label, codes in (
            ("created", report.created),
            ("updated", report.updated),
            ("restored", report.restored),
            ("deprecated", report.deprecated),
        ):
            for code in codes:
                self.stdout.write(f"{label:>10}  {code}")
        if not report.changed:
            self.stdout.write("catalog already in sync")
