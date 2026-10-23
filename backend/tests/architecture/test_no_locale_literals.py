"""
No currency code and no timezone is hard-coded (CONFIGURATION.md § 15, § 18; BUILD_ORDER 5.6).

The bug it prevents: a product built on this core sells in rupees, or runs in Asia/Kolkata, and a
literal "USD" or "America/New_York" deep in a service quietly does the wrong thing. Currency,
timezone and formats are settings (platform → tenant → user), never constants.

How: every str constant in production Python (docstrings excluded) is compared with the ISO-4217
list in core/data/iso4217.txt and with zoneinfo.available_timezones(); TS/TSX string literals in
frontend/src are compared with the same lists by a quote-delimited regex.

Blind spots: a code assembled at runtime ("US" + "D"); a zone without an Area/ part ("Japan",
"EST") — those legacy aliases collide with ordinary words and are left out on purpose; template
literals with interpolation on the frontend. "UTC" is allowed: storage is UTC by rule.
Complementary guard: the frontend formatter rule in eslint.config.mjs, once § 15 is built.

Do NOT silence this by adding an exception — fix the code. An allow-list entry needs a reason.
"""

import re
import zoneinfo
from pathlib import Path

from tests.architecture._ratchet import assert_ratchet
from tests.architecture.sources import (
    BACKEND,
    Hit,
    iter_frontend_sources,
    iter_python_sources,
    parse,
    rel,
    string_constants,
)

CURRENCIES = frozenset(
    line.strip()
    for line in (BACKEND / "core" / "data" / "iso4217.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
)
# Area/Location zones only ("Europe/Paris"); "UTC" and the Etc/ aliases of it are the storage rule.
ZONES = frozenset(
    z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith("Etc/")
)
TS_STRING = re.compile(r"""(["'`])([^"'`\\\n$]{3,40})\1""")

# path::value -> why it is allowed. Do not add an entry without a reason.
ALLOWED: dict[str, str] = {}


def offence(value: str) -> str | None:
    if value in CURRENCIES:
        return "currency"
    if value in ZONES:
        return "timezone"
    return None


def python_hits(files) -> list[Hit]:
    hits = []
    for path in files:
        for node in string_constants(parse(path)):
            if offence(node.value):
                hits.append(Hit(rel(path), node.lineno, node.value))
    return sorted(hits, key=lambda h: (h.path, h.line))


def frontend_hits(files) -> list[Hit]:
    hits = []
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue
            for match in TS_STRING.finditer(line):
                if offence(match.group(2)):
                    hits.append(Hit(rel(path), number, match.group(2)))
    return hits


def test_the_lists_are_loaded():
    assert {"USD", "EUR", "INR", "JPY"} <= CURRENCIES and len(CURRENCIES) > 150
    assert "Asia/Kolkata" in ZONES and "UTC" not in ZONES


def test_no_locale_literals_in_production_code():
    hits = python_hits(iter_python_sources()) + frontend_hits(iter_frontend_sources())
    assert_ratchet(hits, ALLOWED, rule="no_locale_literals")


def test_catches_a_hard_coded_currency_and_zone(tmp_path: Path):
    service = tmp_path / "services.py"
    service.write_text(
        '"""Bills in USD (a docstring is prose, not a value)."""\n'
        'def total(x):\n    return {"amount": x, "currency": "USD"}\n'
        'TZ = "Asia/Kolkata"\nOK = "UTC"\nWORD = "ALLOWED"\n'
    )
    page = tmp_path / "page.tsx"
    page.write_text(
        '// "EUR" in a comment is fine\nconst c = "EUR";\nconst z = \'Europe/Paris\';\n'
    )
    assert [str(h) for h in python_hits([service])] == [
        "services.py:3: USD",
        "services.py:4: Asia/Kolkata",
    ]
    assert [str(h) for h in frontend_hits([page])] == [
        "page.tsx:2: EUR",
        "page.tsx:3: Europe/Paris",
    ]
