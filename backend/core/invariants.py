"""
The invariant pattern (DOMAIN_PRIMITIVES.md § 1.4; BUILD_ORDER 6.5): a `clean()` validator for the
user-facing message, a database CheckConstraint for the truth, and one mapping from the database's
refusal back to a typed error.

A validator alone is bypassed by QuerySet.update(), bulk_create(), a data migration and a shell;
the constraint is what holds. But a raw IntegrityError names a constraint, not a rule, and
escapes as a 500. `invariant_scope()` turns the constraint's refusal into an InvariantViolation
carrying the rule's message, which the API reports as 409 invariant_violated.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from django.db import IntegrityError, transaction


class InvariantViolation(Exception):
    """The database refused a write that would break a stated rule."""

    code = "invariant_violated"

    def __init__(self, constraint: str, message: str) -> None:
        super().__init__(message)
        self.constraint = constraint


# PostgreSQL: ... violates check constraint "name" / unique constraint "name"
# SQLite:     CHECK constraint failed: name  /  UNIQUE constraint failed: table.col
_PG = re.compile(r'violates (?:check|unique|exclusion|foreign key) constraint "([^"]+)"')
_SQLITE = re.compile(r"(?:CHECK|UNIQUE|NOT NULL) constraint failed: (\S+)")


def constraint_name(exc: BaseException) -> str | None:
    """The constraint an IntegrityError names, or None when the backend did not say."""
    text = str(exc)
    match = _PG.search(text) or _SQLITE.search(text)
    return match.group(1) if match else None


def map_integrity_error(exc: IntegrityError, rules: Mapping[str, str]) -> InvariantViolation | None:
    """The typed error for a refusal naming one of `rules` (constraint name -> message)."""
    name = constraint_name(exc)
    if name is None:
        return None
    for constraint, message in rules.items():
        if name == constraint or name.endswith(f".{constraint}"):
            return InvariantViolation(constraint, message)
    return None


@contextmanager
def invariant_scope(rules: Mapping[str, str]) -> Iterator[None]:
    """Run writes inside a savepoint; a refusal by one of `rules` raises InvariantViolation with
    the rule's message. Any other IntegrityError propagates unchanged."""
    try:
        with transaction.atomic():
            yield
    except IntegrityError as exc:
        mapped = map_integrity_error(exc, rules)
        if mapped is None:
            raise
        raise mapped from exc
