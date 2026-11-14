"""
Outbound HTTP and mail go through core.http and core.mail (JOBS_AND_INTEGRATIONS.md § 18, § 27).

Importing an HTTP library, smtplib or a provider SDK anywhere else skips the address vetting, the
timeouts, the redaction and the non-production guard at once. Allowed: core/http/, core/mail/,
core/providers/ (exception translation only) and
any */adapters/ package (where an SDK is wrapped behind core.http.guard.allows()). The allow-list
below names a file and a reason; none is needed today.
"""

import ast

from core.http.policy import OUTBOUND_HTTP_MODULES, OUTBOUND_MAIL_MODULES, OUTBOUND_SDK_MODULES
from tests.architecture.sources import BACKEND, iter_python_sources, parse, rel

FORBIDDEN = (*OUTBOUND_HTTP_MODULES, *OUTBOUND_MAIL_MODULES, *OUTBOUND_SDK_MODULES)
# core/providers imports httpx only to translate its exceptions at the boundary (§ 20).
ALLOWED_DIRS = (
    BACKEND / "core" / "http",
    BACKEND / "core" / "mail",
    BACKEND / "core" / "providers",
)
ALLOWED: dict[str, str] = {}  # "path::module": the reviewed reason


def imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
            found += [(node.lineno, f"{node.module}.{alias.name}") for alias in node.names]
    return found


def forbidden(module: str) -> str | None:
    for name in FORBIDDEN:
        if module == name or module.startswith(name + "."):
            return name
    return None


def test_outbound_http_goes_through_core_http():
    scanned, offenders = 0, []
    for path in iter_python_sources():
        if any(allowed in path.parents for allowed in ALLOWED_DIRS) or "adapters" in path.parts:
            continue
        scanned += 1
        for line, module in imported_modules(parse(path)):
            name = forbidden(module)
            if name and f"{rel(path)}::{name}" not in ALLOWED:
                offenders.append(f"{rel(path)}:{line} imports {module}")
    assert scanned, "scanned no files: the scan is looking in the wrong place"
    assert sorted(set(offenders)) == [], (
        "call other systems through core.http.client(purpose) (or Django mail, which the guard "
        "wraps):\n" + "\n".join(sorted(set(offenders)))
    )


def test_the_scan_sees_each_form():
    source = (
        "import requests\nimport httpx as h\nfrom urllib import request\n"
        "from http.client import HTTPSConnection\nimport smtplib\nfrom urllib.parse import quote\n"
        "import http\n"
    )
    hits = sorted({forbidden(m) for _, m in imported_modules(ast.parse(source))} - {None})
    assert hits == ["http.client", "httpx", "requests", "smtplib", "urllib.request"]


def test_the_allow_list_has_no_dead_entries():
    assert all((BACKEND.parent / key.split("::")[0]).exists() for key in ALLOWED)
