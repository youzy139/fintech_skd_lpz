from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.services.catalog import CatalogStore
from app.services.source_quality_audit import SourceAuditError, audit_source
from market_core.domain.sources import SourceFile


def make_duplicate_source(tmp_path: Path) -> SourceFile:
    path = tmp_path / "records.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at_twitter", "text", "empty"])
        writer.writeheader()
        writer.writerows([
            {"created_at_twitter": "2024-01-01", "text": "same", "empty": ""},
            {"created_at_twitter": "2024-01-01", "text": "same", "empty": ""},
            {"created_at_twitter": "2024-01-02", "text": "other", "empty": ""},
        ])
    return SourceFile.create(tmp_path, path, "social")


def test_read_only_audit_counts_duplicates_and_all_empty_fields(tmp_path: Path):
    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    store.import_file(source)
    records_before = store.list_records(None, None, None, 0, 20)
    second_index, second_payload = store.connection.execute(
        "SELECT record_index, payload_json FROM source_records WHERE source_id = ? ORDER BY record_index LIMIT 1 OFFSET 1",
        (source.id,),
    ).fetchone()
    parsed = json.loads(second_payload)
    store.connection.execute(
        "UPDATE source_records SET payload_json = ? WHERE source_id = ? AND record_index = ?",
        (json.dumps(dict(reversed(list(parsed.items())))), source.id, second_index),
    )
    store.connection.commit()
    table_count = store.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone()[0]

    report = audit_source(database, source.id)

    assert report["audit_status"] == "complete"
    assert report["file"]["scanned_record_count"] == 3
    assert report["duplicate_excess_count"] == 1
    assert report["duplicate_group_count"] == 1
    assert report["duplicate_groups_sample"] == [{
        "first_record_index": min(row["record_index"] for row in records_before["items"]),
        "occurrence_count": 2,
        "additional_record_indices": [second_index],
    }]
    empty = next(field for field in report["fields"] if field["name"] == "empty")
    assert empty == {
        "name": "empty", "present_count": 3, "null_count": 0,
        "empty_string_count": 3, "absent_count": 0, "non_null_count": 0,
    }
    assert report["preaggregated_field_comparison"]["status"] == "match"
    assert store.list_records(None, None, None, 0, 20) == records_before
    assert store.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone()[0] == table_count
    store.close()


def test_audit_marks_partial_import_and_rejects_unknown_file(tmp_path: Path):
    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    store.import_file(source)
    store.connection.execute("UPDATE source_files SET status = 'failed' WHERE id = ?", (source.id,))
    store.connection.commit()

    report = audit_source(database, source.id)
    assert report["audit_status"] == "inconsistent"
    with pytest.raises(SourceAuditError, match="not found"):
        audit_source(database, "missing")
    store.close()


def test_audit_requires_an_existing_sqlite_snapshot(tmp_path: Path):
    with pytest.raises(SourceAuditError, match="does not exist"):
        audit_source(tmp_path / "missing.db", "source")


def test_audit_separates_absent_null_empty_and_falsy_values_and_detects_stale_inventory(tmp_path: Path, monkeypatch):
    from market_core.domain.sources import SourceRecord

    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    rows = [
        SourceRecord(source.id, 0, None, "private body", {"empty": "", "nil": None, "value": 0}),
        SourceRecord(source.id, 1, None, "private body", {"nil": None, "value": False, "space": " "}),
        SourceRecord(source.id, 2, None, "private body", {"value": "0", "space": " "}),
    ]
    monkeypatch.setattr("app.services.catalog.iter_records", lambda _: iter(rows))
    store.import_file(source)
    store.connection.execute("DELETE FROM source_fields WHERE name = 'nil'")
    store.connection.commit()
    version = store.data_version()

    report = audit_source(database, source.id)
    fields = {field["name"]: field for field in report["fields"]}
    assert fields["nil"]["null_count"] == 2 and fields["nil"]["absent_count"] == 1
    assert fields["empty"]["empty_string_count"] == 1 and fields["empty"]["absent_count"] == 2
    assert fields["value"]["non_null_count"] == 3
    assert fields["space"]["non_null_count"] == 2
    assert report["dates"]["undated_records"] == 3
    assert report["duplicate_excess_count"] == 0
    assert report["preaggregated_field_comparison"]["mismatch_names_sample"] == ["nil"]
    assert "private body" not in json.dumps(report)
    assert store.data_version() == version == report["catalog_data_version"]
    store.close()


def test_audit_detects_duplicates_across_batches_and_limits_samples(tmp_path: Path, monkeypatch):
    from market_core.domain.sources import SourceRecord

    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    rows = [SourceRecord(source.id, index, "2024-01-01", "same", {"text": "same"}) for index in range(1001)]
    monkeypatch.setattr("app.services.catalog.iter_records", lambda _: iter(rows))
    store.import_file(source)
    report = audit_source(database, source.id)
    assert report["duplicate_excess_count"] == 1000
    assert report["duplicate_group_count"] == 1
    assert report["duplicate_groups_sample"][0]["occurrence_count"] == 1001
    assert report["duplicate_groups_sample"][0]["additional_record_indices"] == [1, 2, 3, 4, 5]
    assert report["dates"] == {
        "dated_records": 1001, "undated_records": 0,
        "start_date": "2024-01-01", "end_date": "2024-01-01",
    }
    store.close()


def test_audit_keeps_one_snapshot_while_another_connection_changes_records(tmp_path: Path, monkeypatch):
    import sqlite3

    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    store.import_file(source)
    version = store.data_version()
    original_connect = sqlite3.connect
    changed = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        if kwargs.get("uri"):
            def trace(sql):
                if sql.startswith("SELECT COUNT(*) FROM source_records") and not changed:
                    store.connection.execute("DELETE FROM source_records WHERE source_id = ?", (source.id,))
                    store.connection.execute("UPDATE source_files SET record_count = 0 WHERE id = ?", (source.id,))
                    store.connection.commit()
                    changed.append(True)
            connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr("app.services.source_quality_audit.sqlite3.connect", connect)
    report = audit_source(database, source.id)
    assert changed == [True]
    assert report["audit_status"] == "complete"
    assert report["file"]["scanned_record_count"] == 3
    assert report["catalog_data_version"] == version
    assert store.summary()["total_records"] == 0
    store.close()


def test_registered_audit_is_bound_to_imported_content_and_becomes_stale_on_reimport(tmp_path: Path, monkeypatch):
    from market_core.domain.sources import SourceRecord

    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    store.import_file(source)
    report = audit_source(database, source.id)
    stored_hash = store.connection.execute(
        "SELECT content_sha256 FROM source_content_versions WHERE source_id = ?", (source.id,),
    ).fetchone()[0]
    assert report["source_content_sha256"] == stored_hash
    store.register_source_audit(report)
    current = store.file_governance(source.id)["audit_registration"]
    assert current["status"] == "current" and current["report"]["audit_status"] == "complete"

    changed = [SourceRecord(source.id, 0, "2024-01-02", "changed", {"text": "updated"})]
    monkeypatch.setattr("app.services.catalog.iter_records", lambda _: iter(changed))
    store.import_file(source)
    stale = store.file_governance(source.id)["audit_registration"]
    assert stale["status"] == "stale"
    assert stale["audited_content_sha256"] != stale["current_content_sha256"]
    store.close()


def test_audit_registration_rejects_changed_or_incomplete_snapshots(tmp_path: Path):
    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    store.import_file(source)
    report = audit_source(database, source.id)
    report["source_content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="changed during audit"):
        store.register_source_audit(report)
    report["audit_status"] = "inconsistent"
    with pytest.raises(ValueError, match="only complete"):
        store.register_source_audit(report)
    assert store.file_governance(source.id)["audit_registration"]["status"] == "not_registered"
    store.close()


def test_cli_creates_a_complete_report_without_overwriting_outputs(tmp_path: Path, monkeypatch, capsys):
    from scripts import audit_source_quality

    database = tmp_path / "catalog.db"
    store = CatalogStore(database)
    source = make_duplicate_source(tmp_path)
    store.import_file(source)
    store.close()
    output = tmp_path / "server/data/quality-audits/report.json"
    monkeypatch.setattr(audit_source_quality, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["audit_source_quality.py", "--database", str(database),
        "--source-id", source.id, "--output", str(output), "--register"])
    assert audit_source_quality.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["audit_status"] == "complete"
    registered = CatalogStore(database)
    assert registered.file_governance(source.id)["audit_registration"]["status"] == "current"
    registered.close()
    original = output.read_bytes()
    with pytest.raises(SystemExit):
        audit_source_quality.main()
    assert output.read_bytes() == original
    assert len(list(output.parent.iterdir())) == 1
    capsys.readouterr()
