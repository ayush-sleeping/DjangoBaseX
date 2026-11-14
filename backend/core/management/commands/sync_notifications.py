from django.core.management.base import BaseCommand

from core.notifications.engine import sync_matrix


class Command(BaseCommand):
    help = (
        "Seed the notification matrix and test-routing state from code. Inserts missing rows only: "
        "an admin's choice is never overwritten; rows of a removed purpose or channel are deleted."
    )

    def handle(self, *args, **options):
        report = sync_matrix()
        self.stdout.write(f"added {report['added']}, removed {report['removed']}")
