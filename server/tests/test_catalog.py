from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services.catalog import CatalogStore
from market_core.domain.sources import SourceFile


def make_source(tmp_path: Path, rows: list[tuple[str, str]] | None = None) -> SourceFile:
    path = tmp_path / "科技.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at_twitter", "text"])
        writer.writeheader()
        for day, text in rows or [("2024-01-01", "第一条"), ("2024-01-02", "第二条")]:
            writer.writerow({"created_at_twitter": day, "text": text})
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


def test_overview_rebuild_and_latest_pages(tmp_path: Path):
    store = CatalogStore(tmp_path / "catalog.db")
    item = make_source(tmp_path)
    store.import_file(item)
    expected = store.overview("social")
    assert expected["records"] == 2
    assert expected["start_date"] == "2024-01-01"
    assert expected["end_date"] == "2024-01-02"
    assert expected["granularity"] == "day"
    assert expected["trend"] == [{"period": "2024-01-01", "count": 1}, {"period": "2024-01-02", "count": 1}]
    assert expected["fields"] == [{"name": "created_at_twitter", "non_null_count": 2}, {"name": "text", "non_null_count": 2}]

    first = store.list_records(None, None, None, 0, 1, "social")
    second = store.list_records(None, None, None, 1, 1, "social")
    assert first["total"] == 2
    assert first["items"][0]["title"] == "第二条"
    assert second["items"][0]["title"] == "第一条"

    store.connection.execute("DELETE FROM source_daily_stats")
    store.connection.execute("DELETE FROM source_fields")
    assert store.rebuild_statistics() == {"sources": 1, "records": 2}
    assert store.overview("social") == expected
    store.close()


def test_statistics_follow_changed_file_and_empty_source(tmp_path: Path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.import_file(make_source(tmp_path))
    changed = make_source(tmp_path, [("2024-01-01", "第一条"), ("2024-02-01", "第二条"), ("2024-05-01", "")])
    store.import_file(changed)
    overview = store.overview("social")
    assert overview["records"] == 3
    assert overview["granularity"] == "month"
    assert sum(point["count"] for point in overview["trend"]) == 3
    assert {field["name"]: field["non_null_count"] for field in overview["fields"]}["text"] == 2
    assert store.overview("news")["records"] == 0
    assert store.overview("news")["trend"] == []
    store.close()


def test_tag_counts_filtering_and_rebuild(tmp_path: Path):
    store = CatalogStore(tmp_path / "catalog.db")
    item = make_source(tmp_path, [("2024-01-01", "AI 与半导体"), ("2024-01-02", "通胀与加息"), ("2024-01-03", "普通文本")])
    store.import_file(item)
    counts = {entry["tag"]: entry["records"] for entry in store.list_tags("social")}
    assert counts["人工智能"] == 1
    assert counts["半导体"] == 1
    assert counts["通胀"] == 1
    filtered = store.list_records(None, None, "2024-01-01", 0, 20, "social", "人工智能")
    assert filtered["total"] == 1
    assert filtered["items"][0]["title"] == "AI 与半导体"
    assert "人工智能" in filtered["items"][0]["tags"]
    assert store.list_records(None, None, None, 0, 20, "social", "不存在的标签")["total"] == 0
    assert store.rebuild_statistics() == {"sources": 1, "records": 3}
    assert {entry["tag"]: entry["records"] for entry in store.list_tags("social")} == counts
    assert store.list_records(item.id, None, None, 0, 20, tag="人工智能")["total"] == 1
    store.close()


def test_multi_tag_union_intersection_deduplication_and_limit(tmp_path: Path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.import_file(make_source(tmp_path, [("2024-01-01", "AI 与半导体"), ("2024-01-02", "通胀与加息"), ("2024-01-03", "普通文本")]))
    union = store.list_records(None, None, None, 0, 20, "social", tags=["人工智能", "通胀"], match="any")
    assert union["total"] == 2
    assert len(union["items"]) == 2
    intersection = store.list_records(None, None, None, 0, 20, "social", tags=["人工智能", "半导体"], match="all")
    assert intersection["total"] == 1
    assert intersection["items"][0]["title"] == "AI 与半导体"
    assert store.list_records(None, None, None, 0, 20, "social", tags=["人工智能", "通胀"], match="all")["total"] == 0
    assert store.list_records(None, None, None, 0, 20, "social", tags=["人工智能", "人工智能"], match="all")["total"] == 1
    with pytest.raises(ValueError, match="最多同时筛选 5 个标签"):
        store.list_records(None, None, None, 0, 20, "social", tags=[str(index) for index in range(6)])
    store.close()


def test_concurrent_catalog_queries_share_connection_safely(tmp_path: Path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.import_file(make_source(tmp_path, [("2024-01-01", "AI"), ("2024-01-02", "半导体")]))

    def read(index: int):
        if index % 3 == 0:
            assert store.summary()["total_records"] == 2
        elif index % 3 == 1:
            assert store.list_tags("social")
        else:
            assert store.overview("social")["records"] == 2
            assert store.list_records(None, None, None, 0, 20, "social")["total"] == 2

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(read, range(90)))
    store.close()
