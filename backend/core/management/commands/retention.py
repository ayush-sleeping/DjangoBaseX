"""
manage.py retention (BUILD_ORDER 7.5; DATA_LIFECYCLE.md § 6): the same engine the daily job runs,
by hand and for cron.

  retention                      apply every policy except the opt-in ones
  retention --dry-run            count what would go; delete nothing
  retention --status             per policy: rows, oldest, cutoff, eligible, cap (read-only)
  retention --policy KEY         only these policies (repeatable)
  retention --include-opt-in     also the opt-in policies (the audit log)

Last-run time is not shown by --status: runs are job rows (core_job_run) and a CLI run leaves none.
"""

from django.core.management.base import BaseCommand, CommandError

from core.retention import engine


def _when(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


class Command(BaseCommand):
    help = "Delete rows past their registered retention policy. --dry-run deletes nothing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--status", action="store_true", help="Show each policy; change nothing."
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Count what would go; delete nothing."
        )
        parser.add_argument(
            "--policy", action="append", metavar="KEY", help="Only this policy (repeatable)."
        )
        parser.add_argument(
            "--include-opt-in",
            action="store_true",
            help="Also run opt-in policies such as the audit log (core.activity_log).",
        )

    def handle(self, *args, status, dry_run, policy, include_opt_in, **options):
        try:
            if status:
                self._status(policy)
            else:
                self._run(policy, dry_run, include_opt_in)
        except engine.UnknownPolicy as exc:
            raise CommandError(f"unknown retention policy: {exc.args[0]}") from None

    def _run(self, only, dry_run, include_opt_in):
        for result in engine.run(only=only, dry_run=dry_run, include_opt_in=include_opt_in):
            if result.state == engine.DRY_RUN:
                line = f"would delete {result.eligible} (cutoff {_when(result.cutoff)})"
            elif result.state == engine.RAN:
                line = f"deleted {result.deleted} (cutoff {_when(result.cutoff)})"
                line += " TRUNCATED: more remain, run again" if result.truncated else ""
            else:
                line = f"skipped: {result.state}"
            self.stdout.write(f"{result.key}: {line}")

    def _status(self, only):
        header = ("policy", "state", "rows", "oldest", "cutoff", "eligible", "cap", "truncated")
        rows = [header]
        for item in engine.status(only=only):
            rows.append(
                (
                    item.key,
                    item.state,
                    str(item.rows),
                    _when(item.oldest),
                    _when(item.cutoff),
                    str(item.eligible),
                    str(item.max_rows) if item.max_rows else "-",
                    "yes" if item.would_truncate else "no",
                )
            )
        widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
        for row in rows:
            self.stdout.write(
                "  ".join(
                    cell.ljust(width) for cell, width in zip(row, widths, strict=True)
                ).rstrip()
            )
