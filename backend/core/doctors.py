"""
The doctor umbrella (OBSERVABILITY.md § 12): run every registered doctor and judge the findings.

This module names no subsystem (test_umbrella_names_no_subsystem). Each doctor returns Findings by
calling its subsystem's real enforcement code; the umbrella applies the rules that are the same for
all of them:

- a failure fails; an advisory fails only under --strict (or for a key in DOCTOR_STRICT_KEYS);
- a finding listed in the doctor's `known` ledger is backlog, not new breakage, but a doctor with
  backlog never reads "healthy", and --strict requires every backlog to be empty;
- a ledger entry that no longer reproduces is a failure ("fixed or gone: remove it"), or the ledger
  silently turns into decoration;
- a doctor that raises is reported as its own failure and makes the run exit 2: a crashed doctor is
  not a passing doctor.
"""

import time
from dataclasses import dataclass, field

from core.registry import ADVISORY, FAILURE, Doctor, Finding, registry

# Doctors CI runs strictly, once their backlog ledgers are empty (§ 12). Code, not env: moving a
# subsystem to strict is a reviewed change.
DOCTOR_STRICT_KEYS: frozenset[str] = frozenset()

EXIT_OK, EXIT_FAILED, EXIT_CRASHED, EXIT_USAGE = 0, 1, 2, 3


@dataclass
class DoctorResult:
    key: str
    findings: list[Finding] = field(default_factory=list)
    backlog: list[Finding] = field(default_factory=list)
    entries_fixed: list[str] = field(default_factory=list)
    crashed: bool = False
    duration_ms: int = 0

    @property
    def failed(self) -> bool:
        return self.crashed or any(f.severity == FAILURE for f in self.findings)

    @property
    def status(self) -> str:
        if self.crashed:
            return "crashed"
        if self.failed:
            return "failed"
        if self.backlog:
            return f"{len(self.backlog)} known issues remain"  # never "healthy" over a backlog
        if self.findings:
            return "advisories"
        return "healthy"

    def as_dict(self) -> dict:
        return {
            "doctor": self.key,
            "status": self.status,
            "findings": [_finding_dict(f) for f in self.findings],
            "backlog": {
                "size": len(self.backlog),
                "entries": [_finding_dict(f) for f in self.backlog],
                "entries_fixed": list(self.entries_fixed),
            },
            "duration_ms": self.duration_ms,
        }


def _finding_dict(finding: Finding) -> dict:
    return {
        "severity": finding.severity,
        "code": finding.code,
        "subject": finding.subject,
        "message": finding.message,
        "remedy": finding.remedy,
    }


def run_doctor(doctor: Doctor, *, strict: bool = False) -> DoctorResult:
    result = DoctorResult(key=doctor.key)
    started = time.perf_counter()
    try:
        found = list(doctor.fn())
        for finding in found:
            if not isinstance(finding, Finding):
                raise TypeError(f"returned {type(finding).__name__}, not a Finding")
    except Exception as exc:  # noqa: BLE001 — a crashed doctor is reported, never swallowed
        result.crashed = True
        result.findings.append(
            Finding(
                FAILURE,
                "doctor.crashed",
                doctor.key,
                f"the doctor itself raised {type(exc).__name__}: {exc}",
                remedy=f"fix the {doctor.key} doctor; until then nothing it checks is known",
            )
        )
        found = []
    finally:
        result.duration_ms = round((time.perf_counter() - started) * 1000)
    strict = strict or doctor.key in DOCTOR_STRICT_KEYS
    seen = set()
    for finding in found:
        seen.add(finding.ledger_key)
        if finding.ledger_key in doctor.known:
            result.backlog.append(finding)
        elif strict and finding.severity == ADVISORY:
            result.findings.append(_as_failure(finding))
        else:
            result.findings.append(finding)
    if not result.crashed:
        for entry in sorted(doctor.known - seen):
            result.entries_fixed.append(entry)
            result.findings.append(
                Finding(
                    FAILURE,
                    "doctor.ledger_entry_fixed",
                    entry,
                    f"{doctor.key}'s ledger lists {entry!r}, which no longer reproduces",
                    remedy="remove it from the ledger: it is fixed or gone (§ 12, shrink-only)",
                )
            )
    if strict and result.backlog:
        result.findings.append(
            Finding(
                FAILURE,
                "doctor.backlog_not_empty",
                doctor.key,
                f"{len(result.backlog)} known issues remain, and strict requires none",
                remedy="fix them and shrink the ledger",
            )
        )
    return result


def _as_failure(finding: Finding) -> Finding:
    return Finding(FAILURE, finding.code, finding.subject, finding.message, finding.remedy)


def select(only: list[str] | None = None, skip: list[str] | None = None) -> list[Doctor]:
    """The doctors to run, in registration order. KeyError names an unknown key (a usage error)."""
    doctors = registry.doctors.doctors()
    known = {d.key for d in doctors}
    unknown = sorted((set(only or ()) | set(skip or ())) - known)
    if unknown:
        raise KeyError(", ".join(unknown))
    return [d for d in doctors if (not only or d.key in only) and not (skip and d.key in skip)]


def run(doctors: list[Doctor], *, strict: bool = False) -> tuple[list[DoctorResult], int]:
    results = [run_doctor(d, strict=strict) for d in doctors]
    if any(r.crashed for r in results):
        return results, EXIT_CRASHED
    if any(r.failed for r in results):
        return results, EXIT_FAILED
    return results, EXIT_OK
