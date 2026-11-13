from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from market_core.domain.source_quality import canonical_record
from app.services.source_content_version import SourceContentDigest


class SourceAuditError(ValueError):
    pass


def audit_source(database_path: Path, source_id: str) -> dict[str, Any]:
    """Audit one SQLite catalog file using a read-only, transactionally consistent snapshot."""
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise SourceAuditError("catalog database does not exist")

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True, timeout=30)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        source_rows = connection.execute(
            "SELECT id, size, mtime_ns, status, record_count, error_count, updated_at FROM source_files ORDER BY id"
        ).fetchall()
        source = connection.execute(
            "SELECT id, kind, path, status, record_count, size, mtime_ns FROM source_files WHERE id = ?",
            (source_id,),
        ).fetchone()
        if source is None:
            raise SourceAuditError("source file was not found")

        _, kind, path, status, declared_count, size, mtime_ns = source
        catalog_version = hashlib.sha256(repr(source_rows).encode("utf-8")).hexdigest()
        actual_count = connection.execute(
            "SELECT COUNT(*) FROM source_records WHERE source_id = ?", (source_id,)
        ).fetchone()[0]
        stored_fields = dict(connection.execute(
            "SELECT name, non_null_count FROM source_fields WHERE source_id = ?", (source_id,)
        ).fetchall())

        fields: dict[str, list[int]] = {}
        content_digest = SourceContentDigest()
        duplicate_excess = 0
        duplicate_groups = 0
        scanned = 0
        dated = 0
        start_date: str | None = None
        end_date: str | None = None
        with (
            tempfile.TemporaryDirectory(prefix="marketlens-quality-audit-") as scratch,
            closing(sqlite3.connect(Path(scratch) / "signatures.sqlite")) as signatures,
        ):
            signatures.execute("PRAGMA journal_mode = OFF")
            signatures.execute("PRAGMA synchronous = OFF")
            signatures.execute(
                "CREATE TABLE signatures (digest BLOB NOT NULL, canonical BLOB NOT NULL, occurrence_count INTEGER NOT NULL, "
                "first_record_index INTEGER NOT NULL, duplicate_indices TEXT NOT NULL, PRIMARY KEY (digest, canonical)) WITHOUT ROWID"
            )

            cursor = connection.execute(
                "SELECT record_index, event_date, title, payload_json FROM source_records "
                "WHERE source_id = ? ORDER BY record_index",
                (source_id,),
            )
            while batch := cursor.fetchmany(500):
                for record_index, event_date, title, payload_json in batch:
                    try:
                        payload = json.loads(payload_json)
                    except (TypeError, json.JSONDecodeError) as error:
                        raise SourceAuditError("stored record payload is not valid JSON") from error
                    if not isinstance(payload, dict):
                        raise SourceAuditError("stored record payload is not an object")

                    try:
                        canonical = canonical_record(event_date, title, payload)
                    except (ValueError, TypeError) as error:
                        raise SourceAuditError("stored record cannot be represented as finite JSON") from error
                    content_digest.update(record_index, event_date, title, payload)
                    digest = hashlib.sha256(canonical).digest()
                    previous = signatures.execute(
                        "SELECT occurrence_count, duplicate_indices FROM signatures WHERE digest = ? AND canonical = ?",
                        (digest, canonical),
                    ).fetchone()
                    if previous is None:
                        signatures.execute(
                            "INSERT INTO signatures VALUES (?, ?, 1, ?, '[]')", (digest, canonical, record_index)
                        )
                    else:
                        occurrence_count, duplicate_indices = previous
                        indices = json.loads(duplicate_indices)
                        if len(indices) < 5:
                            indices.append(record_index)
                        signatures.execute(
                            "UPDATE signatures SET occurrence_count = ?, duplicate_indices = ? WHERE digest = ? AND canonical = ?",
                            (occurrence_count + 1, json.dumps(indices), digest, canonical),
                        )
                        duplicate_excess += 1
                        if occurrence_count == 1:
                            duplicate_groups += 1

                    for name, value in payload.items():
                        counts = fields.setdefault(name, [len(fields), 0, 0, 0, 0])
                        counts[1] += 1
                        if value is None:
                            counts[2] += 1
                        elif value == "":
                            counts[3] += 1
                        else:
                            counts[4] += 1
                    scanned += 1
                    if event_date:
                        dated += 1
                        start_date = min(start_date, event_date) if start_date else event_date
                        end_date = max(end_date, event_date) if end_date else event_date

            signature_samples = signatures.execute(
                "SELECT first_record_index, occurrence_count, duplicate_indices FROM signatures "
                "WHERE occurrence_count > 1 ORDER BY first_record_index LIMIT 20"
            ).fetchall()

        audited_fields = [
            {
                "name": name,
                "present_count": values[1],
                "null_count": values[2],
                "empty_string_count": values[3],
                "absent_count": scanned - values[1],
                "non_null_count": values[4],
            }
            for name, values in sorted(fields.items(), key=lambda item: (item[1][0], item[0]))
        ]
        audited_non_null = {field["name"]: field["non_null_count"] for field in audited_fields}
        mismatch_names = sorted(
            name for name in set(stored_fields) | set(audited_non_null)
            if stored_fields.get(name) != audited_non_null.get(name)
        )
        complete = status == "imported" and declared_count == actual_count == scanned
        return {
            "schema": "source-record-audit-v1",
            "audit_version": "canonical-record-v1",
            "scope": "one-file-within-sqlite-catalog-snapshot",
            "catalog_data_version": catalog_version,
            "source_content_sha256": content_digest.hexdigest(),
            "audit_status": "complete" if complete else "inconsistent",
            "file": {
                "id": source_id,
                "kind": kind,
                "path": path,
                "status": status,
                "declared_record_count": declared_count,
                "catalog_record_count": actual_count,
                "scanned_record_count": scanned,
                "size": size,
                "mtime_ns": mtime_ns,
            },
            "record_counts_match": declared_count == actual_count == scanned,
            "dates": {
                "dated_records": dated, "undated_records": scanned - dated,
                "start_date": start_date, "end_date": end_date,
            },
            "unique_fingerprints": scanned - duplicate_excess,
            "duplicate_excess_count": duplicate_excess,
            "duplicate_group_count": duplicate_groups,
            "duplicate_groups_sample": [
                {
                    "first_record_index": first_index,
                    "occurrence_count": occurrence_count,
                    "additional_record_indices": json.loads(indices),
                }
                for first_index, occurrence_count, indices in signature_samples
            ],
            "field_inventory_count": len(audited_fields),
            "fields": audited_fields,
            "preaggregated_field_comparison": {
                "status": "match" if not mismatch_names else "different",
                "stored_field_count": len(stored_fields),
                "audited_field_count": len(audited_non_null),
                "mismatch_count": len(mismatch_names),
                "mismatch_names_sample": mismatch_names[:20],
            },
            "limitations": [
                "Audits parsed records in this SQLite snapshot, not original source bytes or an active ClickHouse generation.",
                "Duplicate identity is event date, title, and the complete parsed payload with object keys sorted; row index is excluded. SHA-256 indexes candidates and full canonical bytes confirm equality.",
                "Semantic validity, required-field rules, cross-file duplicates, and source-specific meaning are not evaluated.",
                "Field absence, null, and empty strings are counted separately; whitespace strings and zero values are non-null.",
                "Dates retain the existing parser's event-date interpretation; publication-time semantics are not independently verified.",
            ],
        }
    except sqlite3.Error as error:
        raise SourceAuditError("catalog snapshot could not be read consistently") from error
    finally:
        if connection is not None:
            connection.close()
