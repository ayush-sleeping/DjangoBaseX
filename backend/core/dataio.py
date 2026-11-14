"""
Import/export registry (DOMAIN_PRIMITIVES.md § 6). An app registers a DataSpec; this engine owns
the file formats, the injection guard, dry-run, the row-level error report and idempotence.

- Export: CSV (UTF-8 with BOM; a cell starting = + - @ tab or CR is prefixed with ') for people,
  and a JSON bundle ({"_meta": {...}, "<spec key>": [rows]}) for moving an environment.
- Import: every row goes through the spec's `upsert`, which calls the resource's own service;
  there is no raw ORM write here. A row error is reported with its row number and does not stop
  the other rows. dry_run=True runs the REAL services inside a transaction that is rolled back, so
  the report is what a real import would do, validators and audit included.
- Idempotent: a row's natural key finds its existing record; a re-import of the same file reports
  every row "unchanged".
- Permissions: the caller must hold the spec's export / import code. Bundle, row and byte size
  are capped (MAX_ROWS) and the cap is an error, never a silent truncation.

Not built (TECH_DEBT): XLSX (needs a dependency), preview tokens/409 stale preview, foreign-key
remapping, job-mode for large files, a never-export floor beyond the specs' own `fields`.
"""

import csv
import io
import json
from datetime import UTC, datetime

from django.db import transaction

from core import audit
from core.registry import registry

BUNDLE_FORMAT = "djx-bundle"
BUNDLE_VERSION = 1
MAX_ROWS = 10_000
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class DataioError(Exception):
    code = "dataio_error"


class UnknownSpec(DataioError):
    code = "unknown_data_spec"


class PermissionRefused(DataioError):
    code = "permission_denied"


class BadFile(DataioError):
    code = "bad_file"


def _spec(key: str):
    spec = registry.dataio.get(key)
    if spec is None:
        raise UnknownSpec(f"{key!r} is not a registered import/export resource")
    return spec


def _require(user, code: str) -> None:
    if user is None or not user.has_perm(code):
        raise PermissionRefused(f"requires {code}")


# --- Export --------------------------------------------------------------------------------------


def escape_cell(value) -> str:
    """CSV/formula injection: text a spreadsheet would run is made inert with a leading '."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _plain(row: dict, fields: tuple) -> dict:
    return {name: row.get(name) for name in fields}


def export_rows(key: str, user) -> list[dict]:
    spec = _spec(key)
    _require(user, spec.export_permission)
    rows = [_plain(r, spec.fields) for r in spec.rows(user)]
    if len(rows) > MAX_ROWS:
        raise DataioError(f"{len(rows)} rows is above the {MAX_ROWS} row export limit")
    return rows


def export_csv(key: str, user) -> bytes:
    spec = _spec(key)
    rows = export_rows(key, user)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(spec.fields)
    for row in rows:
        writer.writerow(
            [escape_cell(json.dumps(v) if isinstance(v, (dict, list)) else v) for v in row.values()]
        )
    audit.log_activity("core.dataio.exported", actor=user, spec=key, format="csv", rows=len(rows))
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


def export_bundle(keys: list[str], user) -> dict:
    bundle: dict = {
        "_meta": {
            "format": BUNDLE_FORMAT,
            "format_version": BUNDLE_VERSION,
            "specs": sorted(keys),
            "exported_at": datetime.now(UTC).isoformat(),
            "counts": {},
        }
    }
    for key in sorted(keys):
        rows = export_rows(key, user)
        bundle[key] = rows
        bundle["_meta"]["counts"][key] = len(rows)
    audit.log_activity(
        "core.dataio.exported",
        actor=user,
        spec=",".join(sorted(keys)),
        format="json",
        rows=sum(bundle["_meta"]["counts"].values()),
    )
    return bundle


# --- Import --------------------------------------------------------------------------------------


def parse_csv(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{k: _unescape(v) for k, v in row.items()} for row in rows]


def _unescape(value):
    """Undo escape_cell so an exported file round-trips; a user-typed leading ' on a formula-like
    cell is the same thing."""
    if isinstance(value, str) and value.startswith("'") and value[1:].startswith(_FORMULA_PREFIXES):
        return value[1:]
    return value


def parse_bundle(data: bytes | str) -> dict:
    try:
        bundle = json.loads(data)
    except (ValueError, TypeError) as exc:
        raise BadFile("not valid JSON") from exc
    meta = bundle.get("_meta") if isinstance(bundle, dict) else None
    if not isinstance(meta, dict) or meta.get("format") != BUNDLE_FORMAT:
        raise BadFile(f"not a {BUNDLE_FORMAT} bundle (missing or foreign _meta.format)")
    if meta.get("format_version") != BUNDLE_VERSION:
        raise BadFile(f"unsupported bundle version {meta.get('format_version')!r}")
    return bundle


def import_rows(key: str, rows: list[dict], *, actor, dry_run: bool = True) -> dict:
    """
    {"created", "updated", "unchanged", "errors": [{"row", "message"}], "dry_run"}. Row numbers
    are 1-based positions in `rows`. Dry run by default: committing is a deliberate choice.
    """
    spec = _spec(key)
    _require(actor, spec.import_permission)
    if len(rows) > MAX_ROWS:
        raise DataioError(f"{len(rows)} rows is above the {MAX_ROWS} row import limit")
    report: dict = {"created": 0, "updated": 0, "unchanged": 0, "errors": [], "dry_run": dry_run}
    with audit.batch(), transaction.atomic():
        for number, row in enumerate(rows, start=1):
            unknown = sorted(set(row) - set(spec.fields))
            missing = [k for k in spec.natural_key if row.get(k) in (None, "")]
            if unknown or missing:
                report["errors"].append(
                    {
                        "row": number,
                        "message": (f"unknown columns {unknown}. " if unknown else "")
                        + (f"missing natural key {missing}." if missing else ""),
                    }
                )
                continue
            try:
                with transaction.atomic():
                    outcome = spec.upsert(row, actor=actor)
            except ValueError as exc:
                report["errors"].append({"row": number, "message": str(exc)})
                continue
            report[outcome] += 1
        if not dry_run:
            audit.log_activity(
                "core.dataio.imported",
                actor=actor,
                spec=key,
                created=report["created"],
                updated=report["updated"],
                unchanged=report["unchanged"],
                errors=len(report["errors"]),
            )
        if dry_run:
            transaction.set_rollback(True)
    return report


# --- Lookups: the worked example ----------------------------------------------------------------

LOOKUP_FIELDS = ("set_key", "key", "label", "sort_order", "is_active")


def _lookup_rows(user):
    from core.models import LookupValue

    for row in LookupValue.objects.order_by("set_key", "sort_order", "key"):
        yield {name: getattr(row, name) for name in LOOKUP_FIELDS}


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _lookup_upsert(row: dict, *, actor) -> str:
    from core import lookups
    from core.models import LookupValue

    try:
        changes = {}
        if row.get("label") not in (None, ""):
            changes["label"] = str(row["label"])
        if row.get("sort_order") not in (None, ""):
            changes["sort_order"] = int(row["sort_order"])
        if row.get("is_active") not in (None, ""):
            changes["is_active"] = _bool(row["is_active"])
        existing = LookupValue.objects.filter(set_key=row["set_key"], key=row["key"]).first()
        if existing is None:
            lookups.set_lookup_value(
                row["set_key"], row["key"], actor=actor, create=True, **changes
            )
            return "created"
        differing = {k: v for k, v in changes.items() if getattr(existing, k) != v}
        if not differing:
            return "unchanged"
        lookups.set_lookup_value(row["set_key"], row["key"], actor=actor, **differing)
        return "updated"
    except (lookups.LookupError_, TypeError) as exc:
        raise ValueError(str(exc)) from exc


def register_core_specs(registry_) -> None:
    from core.registry import DataSpec

    registry_.dataio.register(
        DataSpec(
            key="core.lookups",
            label="Lookup values",
            fields=LOOKUP_FIELDS,
            natural_key=("set_key", "key"),
            rows=_lookup_rows,
            upsert=_lookup_upsert,
            export_permission="settings.lookups.manage",
            import_permission="settings.lookups.manage",
        )
    )
