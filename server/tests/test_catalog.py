from __future__ import annotations

import csv
from pathlib import Path

from app.services.catalog import CatalogStore
from market_core.domain.sources import SourceFile


def make_source(tmp_path: Path) -> SourceFile:
    path = tmp_path / "科技.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at_twitter", "text"])
        writer.writeheader()
        writer.writerow({"created_at_twitter": "2024-01-01", "text": "第一条"})
        writer.writerow({"created_at_twitter": "2024-01-02", "text": "第二条"})
    return SourceFile.create(tmp_path, path, "social")


def test_import_query_and_incremental_skip(tmp_path: Path):
    store = CatalogStore(tmp_path / "catalog.db")
    item = make_source(tmp_path)
    assert store.import_file(item)["record_count"] == 2
    assert store.is_unchanged(item)
    assert store.summary()["total_records"] == 2
    files = store.list_files("social", "科技", 0, 10)
    assert files["total"] == 1
    records = store.list_records(item.id, "第二", "2024-01-02", 0, 10)
    assert records["total"] == 1
    assert records["items"][0]["payload"]["text"] == "第二条"
    store.close()
