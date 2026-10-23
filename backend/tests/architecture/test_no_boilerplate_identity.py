"""
The boilerplate's own name is the shipped default of nothing (CONFIGURATION.md § 7, § 18).

Every product copied from this repository runs the core below. If the core spells the boilerplate's
name or its old literal cookie prefix, every product wears it: in page titles, the OpenAPI title, an
authenticator app's issuer label. Identity derives from PRODUCT_NAME; the shipped defaults live in
one module per half (core/identity.py, src/core/lib/identity-defaults.ts) and say "Unnamed product".
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# The code every product runs. Tests are excluded: a test may name anything it needs as a control.
SCANNED = (
    "backend/core",
    "backend/users",
    "backend/rbac",
    "backend/config",
    "frontend/src/core",
    "frontend/src/app/(core)",
    "frontend/src/app/layout.tsx",
)
SUFFIXES = {".py", ".ts", ".tsx"}
FORBIDDEN = (
    (re.compile(r"djangobasex", re.IGNORECASE), "the boilerplate's name"),
    # The old shipped cookie prefix as a whole string literal. System check ids ("dbx.E005") and
    # plugin packages ("djx_…") are identifiers of the platform, not product identity.
    (re.compile(r"""["']dbx["']"""), "the old literal cookie prefix"),
)


def scanned_files(roots=SCANNED):
    for root in roots:
        path = REPO / root
        candidates = [path] if path.is_file() else path.rglob("*")
        for file in candidates:
            if file.suffix not in SUFFIXES or not file.is_file():
                continue
            parts = file.relative_to(REPO).parts
            if "tests" in parts or "__pycache__" in parts or file.name.startswith("test_"):
                continue
            yield file


def offences(files, base: Path = REPO) -> list[str]:
    found = []
    for file in files:
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern, what in FORBIDDEN:
                if pattern.search(line):
                    found.append(f"{file.relative_to(base)}:{number}: {what}: {line.strip()}")
    return found


def test_the_scan_covers_real_code():
    files = {f.relative_to(REPO).as_posix() for f in scanned_files()}
    assert "backend/config/settings.py" in files
    assert "frontend/src/core/lib/api.ts" in files
    assert "frontend/src/app/layout.tsx" in files
    assert not any("/tests/" in f for f in files)


def test_core_never_spells_the_boilerplate_identity():
    found = offences(scanned_files())
    assert not found, (
        "Identity must derive from PRODUCT_NAME (CONFIGURATION.md § 7), never be spelled out:\n  "
        + "\n  ".join(found)
    )


def test_the_scan_catches_a_planted_name(tmp_path):
    """Positive control: the patterns fire on exactly the shapes they exist for."""
    planted = tmp_path / "views.py"
    planted.write_text(
        'TITLE = "DjangoBaseX API"\nPREFIX = "dbx"\nCHECK = "dbx.E005"\nAPP = "djx_notes"\n'
    )
    found = [line.split(": ", 1)[1] for line in offences([planted], base=tmp_path)]
    assert found == [
        'the boilerplate\'s name: TITLE = "DjangoBaseX API"',
        'the old literal cookie prefix: PREFIX = "dbx"',
    ]
