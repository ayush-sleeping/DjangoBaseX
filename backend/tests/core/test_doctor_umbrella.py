"""The doctor umbrella (OBSERVABILITY.md § 12): exit codes, the JSON schema, --strict, the backlog
ledger, and an umbrella that names no subsystem."""

import ast
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

import core.doctors
from core.doctors import run_doctor
from core.registry import ADVISORY, FAILURE, Doctor, Finding, Registry, RegistryError

BACKEND = Path(__file__).resolve().parents[2]


def finding(severity=FAILURE, code="thing.broken", subject="x"):
    return Finding(severity, code, subject, "it is broken", remedy="fix it")


def doctor(key="sample", findings=(), known=frozenset(), fn=None):
    return Doctor(
        key=key,
        fn=fn or (lambda: list(findings)),
        owner="tests",
        description="A test doctor.",
        known=known,
    )


@pytest.fixture
def doctors(monkeypatch):
    """Replace the registered doctors with these, for the command."""

    def install(*items):
        fresh = Registry()
        for item in items:
            fresh.doctors.register(item)
        monkeypatch.setattr(core.doctors, "registry", fresh)

    return install


def run_command(*args) -> tuple[int, str]:
    out = StringIO()
    try:
        call_command("doctor", *args, stdout=out, stderr=StringIO())
    except SystemExit as exc:
        return exc.code, out.getvalue()
    return 0, out.getvalue()


# --- Exit codes ----------------------------------------------------------------------------------


def test_clean_exits_0(doctors):
    doctors(doctor())
    assert run_command()[0] == 0


def test_a_failure_exits_1(doctors):
    doctors(doctor(findings=[finding()]))
    assert run_command()[0] == 1


def test_an_advisory_alone_exits_0(doctors):
    doctors(doctor(findings=[finding(ADVISORY)]))
    assert run_command()[0] == 0


def test_crashing_doctor_exits_2_and_is_reported(doctors):
    def boom():
        raise RuntimeError("the doctor itself broke")

    doctors(doctor(), doctor("broken", fn=boom), doctor("failing", findings=[finding()]))
    code, out = run_command("--json")
    assert code == 2  # a crash outranks an ordinary failure
    report = {d["doctor"]: d for d in json.loads(out)["doctors"]}
    assert report["broken"]["status"] == "crashed"
    assert report["broken"]["findings"][0]["code"] == "doctor.crashed"
    assert report["sample"]["status"] == "healthy"  # the others still ran


def test_a_doctor_returning_non_findings_has_crashed(doctors):
    doctors(doctor(fn=lambda: ["just a string"]))
    assert run_command()[0] == 2


def test_an_unknown_key_is_a_usage_error_exit_3(doctors):
    doctors(doctor())
    assert run_command("--only", "nope")[0] == 3


def test_a_bad_flag_is_a_usage_error_exit_3(doctors, capsys):
    doctors(doctor())
    from django.core.management import ManagementUtility

    with pytest.raises(SystemExit) as exc:
        ManagementUtility(["manage.py", "doctor", "--no-such-flag"]).execute()
    assert exc.value.code == 3


def test_only_and_skip(doctors):
    doctors(doctor("a"), doctor("b", findings=[finding()]))
    assert run_command("--only", "a")[0] == 0
    assert run_command("--skip", "b")[0] == 0
    assert run_command("--only", "a,b")[0] == 1


# --- JSON


def test_json_schema_stable(doctors):
    doctors(doctor(findings=[finding()], known=frozenset({"thing.known:y"})))
    core.doctors.registry.doctors.get("sample")  # sealed
    _, out = run_command("--json")
    payload = json.loads(out)
    assert set(payload) == {"exit_code", "doctors"}
    entry = payload["doctors"][0]
    assert set(entry) == {"doctor", "status", "findings", "backlog", "duration_ms"}
    assert set(entry["backlog"]) == {"size", "entries", "entries_fixed"}
    assert set(entry["findings"][0]) == {"severity", "code", "subject", "message", "remedy"}


# --- Strict and the backlog ledger ------------------------------------------------------------


def test_strict_fails_on_advisory_and_nonempty_backlog():
    advisory = doctor(findings=[finding(ADVISORY)])
    assert not run_doctor(advisory).failed
    assert run_doctor(advisory, strict=True).failed

    backlog = doctor(findings=[finding(subject="old")], known=frozenset({"thing.broken:old"}))
    plain = run_doctor(backlog)
    assert not plain.failed and plain.status == "1 known issues remain"  # never "healthy"
    strict = run_doctor(backlog, strict=True)
    assert strict.failed
    assert "doctor.backlog_not_empty" in {f.code for f in strict.findings}


def test_a_finding_outside_the_ledger_fails():
    d = doctor(findings=[finding(subject="new")], known=frozenset({"thing.broken:new2"}))
    result = run_doctor(d)
    assert result.failed and {f.subject for f in result.findings} >= {"new"}


def test_fixed_ledger_entry_is_a_failure():
    d = doctor(findings=[], known=frozenset({"thing.broken:gone"}))
    result = run_doctor(d)
    assert result.failed
    assert result.entries_fixed == ["thing.broken:gone"]
    assert result.findings[0].code == "doctor.ledger_entry_fixed"


def test_a_strict_key_runs_strictly_without_the_flag(monkeypatch):
    monkeypatch.setattr(core.doctors, "DOCTOR_STRICT_KEYS", frozenset({"sample"}))
    assert run_doctor(doctor(findings=[finding(ADVISORY)])).failed


# --- The registry


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "Bad-Key"},
        {"fn": "not callable"},
        {"owner": " "},
        {"description": ""},
        {"known": {"a:b"}},  # a set, not a frozenset literal
    ],
)
def test_malformed_doctors_are_refused(bad):
    values = {"key": "ok", "fn": list, "owner": "tests", "description": "A test doctor."}
    with pytest.raises(RegistryError):
        Registry().doctors.register(Doctor(**(values | bad)))


def test_a_duplicate_key_is_refused():
    registry = Registry()
    registry.doctors.register(doctor())
    with pytest.raises(RegistryError, match="already registered"):
        registry.doctors.register(doctor())


def test_the_shipped_doctors_are_registered():
    from core.registry import registry

    assert {"dataplane", "queue", "schedule"} <= {d.key for d in registry.doctors.doctors()}


# --- The umbrella names no subsystem

UMBRELLA = ("core/doctors.py", "core/management/commands/doctor.py")
SUBSYSTEM_WORDS = ("dataplane", "queue", "schedule", "celery", "permission", "jobs", "migration")


def test_umbrella_names_no_subsystem():
    """The umbrella runs what is registered; a subsystem name in it is a second list."""
    offenders = []
    for rel in UMBRELLA:
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            text = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                text = node.value
            elif isinstance(node, (ast.ImportFrom)):
                text = node.module or ""
            elif isinstance(node, ast.Name):
                text = node.id
            if text and any(word in text.lower() for word in SUBSYSTEM_WORDS):
                offenders.append(f"{rel}:{node.lineno} {text!r}")
    assert offenders == []


def test_the_dataplane_doctor_maps_fatal_to_failure_and_warn_to_advisory(monkeypatch):
    from core import dataplane

    evaluated = [
        dataplane.Evaluated("core.a", "A", dataplane.FATAL, "no admin", "create one", 1),
        dataplane.Evaluated("core.b", "B", dataplane.WARN, "odd", "look", 1),
        dataplane.Evaluated("core.c", "C", dataplane.OK, "", "", 1),
    ]
    monkeypatch.setattr(dataplane, "evaluate", lambda fresh=False: evaluated)
    found = dataplane.doctor_findings()
    assert [(f.severity, f.subject, f.remedy) for f in found] == [
        (FAILURE, "core.a", "create one"),
        (ADVISORY, "core.b", "look"),
    ]
