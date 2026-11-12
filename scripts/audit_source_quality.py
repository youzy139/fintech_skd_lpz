from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.services.source_quality_audit import SourceAuditError, audit_source


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only per-file audit of one SQLite catalog snapshot")
    parser.add_argument("--database", required=True, type=Path, help="SQLite catalog database; distributed ClickHouse is not read")
    parser.add_argument("--source-id", required=True, help="Imported source file identifier")
    parser.add_argument("--output", type=Path, help="Optional JSON path under server/data/quality-audits")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.source_id):
        parser.error("--source-id must contain only letters, digits, underscore, or hyphen")

    output_root = (ROOT / "server/data/quality-audits").resolve()
    if args.output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output_path = output_root / f"{args.source_id}-{timestamp}.json"
    else:
        output_path = args.output.resolve()
        if not output_path.is_relative_to(output_root):
            parser.error("--output must be inside server/data/quality-audits")
    if output_path.exists():
        parser.error("output already exists; choose a new path")
    database_path = args.database.resolve()
    if output_path in {database_path, Path(str(database_path) + "-wal"), Path(str(database_path) + "-shm")}:
        parser.error("output cannot replace the input database or its sidecars")

    try:
        report = audit_source(args.database, args.source_id)
    except SourceAuditError as error:
        parser.error(str(error))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.link(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    print(json.dumps({
        "output": str(output_path),
        "audit_status": report["audit_status"],
        "scanned_records": report["file"]["scanned_record_count"],
        "duplicate_excess_count": report["duplicate_excess_count"],
        "duplicate_group_count": report["duplicate_group_count"],
        "field_inventory_count": report["field_inventory_count"],
    }, ensure_ascii=False))
    return 0 if report["audit_status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
