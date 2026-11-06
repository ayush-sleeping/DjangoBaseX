"""
manage.py doctor: run every registered doctor (OBSERVABILITY.md § 12).

    doctor [--json] [--only k,…] [--skip k,…] [--strict] [--fatal-only]

Exit 0 clean · 1 at least one failure · 2 a doctor itself crashed · 3 usage error. Run by CI, by
the deploy driver's validate step and by an operator at 2 a.m.: one command, so it gets run.
"""

import json
import sys

from django.core.management.base import BaseCommand

from core.doctors import EXIT_USAGE, run, select
from core.registry import ADVISORY


def _keys(value: str | None) -> list[str]:
    return [k.strip() for k in (value or "").split(",") if k.strip()]


class Command(BaseCommand):
    help = "Run every registered doctor. Exit 0 clean, 1 failure, 2 a doctor crashed, 3 usage."

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)

        def usage_error(message):
            parser.print_usage(sys.stderr)
            sys.stderr.write(f"doctor: error: {message}\n")
            raise SystemExit(EXIT_USAGE)

        parser.error = usage_error
        return parser

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="the stable JSON schema, for CI")
        parser.add_argument("--only", help="comma-separated doctor keys to run")
        parser.add_argument("--skip", help="comma-separated doctor keys to leave out")
        parser.add_argument(
            "--strict",
            action="store_true",
            help="advisories fail, and every backlog ledger must be empty",
        )
        parser.add_argument(
            "--fatal-only", action="store_true", help="print failures only, not advisories"
        )

    def handle(self, *args, **options):
        try:
            doctors = select(_keys(options["only"]), _keys(options["skip"]))
        except KeyError as exc:
            self.stderr.write(f"doctor: error: unknown doctor key(s): {exc.args[0]}")
            raise SystemExit(EXIT_USAGE) from None
        results, code = run(doctors, strict=options["strict"])
        if options["json"]:
            payload = {"exit_code": code, "doctors": [r.as_dict() for r in results]}
            self.stdout.write(json.dumps(payload, indent=2, default=str))
        else:
            for result in results:
                self._print(result, fatal_only=options["fatal_only"])
        if code:
            raise SystemExit(code)

    def _print(self, result, *, fatal_only: bool) -> None:
        style = self.style.ERROR if result.failed else self.style.SUCCESS
        self.stdout.write(style(f"{result.key}: {result.status} ({result.duration_ms} ms)"))
        for finding in result.findings:
            if fatal_only and finding.severity == ADVISORY:
                continue
            self.stdout.write(f"  {finding.severity.upper()} {finding.code} [{finding.subject}]")
            self.stdout.write(f"      {finding.message}")
            if finding.remedy:
                self.stdout.write(f"      fix: {finding.remedy}")
        for finding in result.backlog:
            self.stdout.write(f"  KNOWN {finding.code} [{finding.subject}]")
