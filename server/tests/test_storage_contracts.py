from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from app.services.catalog import CatalogStore
from app.services.contracts import CatalogReader, CatalogStorage, CatalogWriter, SnapshotStorage
from app.services.migration_baseline import build_baseline, compare_baselines, write_baseline
from app.services.storage import SnapshotStore
from market_core.domain.sources import SourceFile


def populated_database(tmp_path: Path) -> Path:
    path = tmp_path / "科技.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at_twitter", "text"])
        writer.writeheader()
        writer.writerow({"created_at_twitter": "2024-01-01", "text": "AI 与半导体"})
        writer.writerow({"created_at_twitter": "2024-01-02", "text": "通胀与加息"})
    source = SourceFile.create(tmp_path, path, "social")
    database = tmp_path / "catalog.db"
    catalog = CatalogStore(database)
    catalog.import_file(source)
    catalog.close()
    snapshots = SnapshotStore(database)
    snapshots.save("states", [{"date": "2024-01-02", "label": "测试状态"}])
    snapshots.close()
    return database


def test_sqlite_stores_satisfy_storage_contracts(tmp_path: Path):
    catalog = CatalogStore(tmp_path / "catalog.db")
    snapshots = SnapshotStore(tmp_path / "snapshots.db")
    assert isinstance(catalog, CatalogReader)
    assert isinstance(catalog, CatalogWriter)
    assert isinstance(catalog, CatalogStorage)
    assert isinstance(snapshots, SnapshotStorage)
    catalog.close()
    snapshots.close()


def test_baseline_is_repeatable_and_ignores_generation_time(tmp_path: Path):
    database = populated_database(tmp_path)
    expected = build_baseline(database)
    actual = build_baseline(database)
    expected["generated_at"] = "不参与业务比较的生成时间"
    assert compare_baselines(expected, actual) == []
    assert actual["payload"]["queries"]["summary"]["total_records"] == 2
    assert actual["payload"]["record_inventory"][0]["records_sha256"]
    assert actual["payload"]["snapshots"][0]["key"] == "states"
    output = tmp_path / "nested" / "baseline.json"
    write_baseline(actual, output)
    assert json.loads(output.read_text(encoding="utf-8"))["payload"] == actual["payload"]


def test_baseline_detects_content_change_with_unchanged_record_count(tmp_path: Path):
    database = populated_database(tmp_path)
    expected = build_baseline(database)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE source_records SET payload_json = ? WHERE record_index = 0", (json.dumps({"created_at_twitter": "2024-01-01", "text": "被修改的内容"}, ensure_ascii=False),))
    connection.commit()
    connection.close()
    differences = compare_baselines(expected, build_baseline(database))
    assert any("records_sha256" in difference for difference in differences)
    assert any("payload" in difference for difference in differences)


def test_baseline_options_and_invalid_page_size(tmp_path: Path):
    database = populated_database(tmp_path)
    baseline = build_baseline(database, query_limit=1, include_record_digests=False)
    assert baseline["payload"]["queries"]["records:all"]["limit"] == 1
    assert baseline["payload"]["record_inventory"][0]["records_sha256"] is None
    assert compare_baselines(baseline, build_baseline(database, query_limit=1, include_record_digests=False)) == []
    with pytest.raises(ValueError, match="1 到 100"):
        build_baseline(database, query_limit=0)
