"""
Import holidays into the business calendar from an ICS file (DOMAIN_PRIMITIVES.md § 4).

    uv run python manage.py import_holidays holidays.ics

All-day events become non-working days. Idempotent: a date that already has a row is left alone.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.business_calendar import CalendarError, import_holidays


class Command(BaseCommand):
    help = "Import all-day ICS events as holidays. Existing dates are kept."

    def add_arguments(self, parser):
        parser.add_argument("path", help="An .ics file")

    def handle(self, *args, **options):
        try:
            text = Path(options["path"]).read_text(encoding="utf-8")
        except OSError as exc:
            raise CommandError(f"cannot read {options['path']}: {exc}") from exc
        try:
            result = import_holidays(text)
        except CalendarError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"holidays: {result['created']} added, {result['skipped']} already known")
