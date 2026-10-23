"""
manage.py dataplane [--fatal-only] [--json]: evaluate the data-plane checks fresh (OBSERVABILITY
§ 7).

Exit 1 when any check is fatal (or, without --fatal-only, when any is not ok). This is the
pre-exec gate a web entrypoint runs in a production-like environment; the doctor umbrella
(BUILD_ORDER 7.2) wraps it later. Not a Django system check: those never run under gunicorn.
"""

import json

from django.core.management.base import BaseCommand

from core import dataplane


class Command(BaseCommand):
    help = "Evaluate the data-plane self-checks; exit 1 on fatal (any non-ok without --fatal-only)."

    def add_arguments(self, parser):
        parser.add_argument("--fatal-only", action="store_true", help="exit 1 only on fatal")
        parser.add_argument("--json", action="store_true", help="print the results as JSON")

    def handle(self, *args, **options):
        results = dataplane.evaluate(fresh=True)
        if options["json"]:
            self.stdout.write(json.dumps([r.as_dict() for r in results], indent=2))
        else:
            for r in results:
                line = f"{r.status.upper():<5} {r.key}: {r.detail or r.description}"
                if r.remedy:
                    line += f"\n      fix: {r.remedy}"
                self.stdout.write(line)
        failing = {dataplane.FATAL} if options["fatal_only"] else {dataplane.FATAL, dataplane.WARN}
        if any(r.status in failing for r in results):
            raise SystemExit(1)
