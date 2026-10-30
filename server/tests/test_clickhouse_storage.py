from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.catalog import CatalogStore
from app.services.clickhouse_migration import ClickHouseMigrator
from app.services.clickhouse_store import ANALYTIC_TABLES, ClickHouseCatalogStore, Parameters, insert_blocks
from app.services.mysql_metadata import sql_statements
from app.services.storage import SnapshotStore
from market_core.domain.sources import SourceFile


class FakeClickHouse:
    def __init__(self):
        self.rows: dict[str, list[tuple]] = {}
        self.commands: list[str] = []
        self.queries: list[str] = []

    def command(self, statement: str):
        self.commands.append(statement)
        if statement.startswith("TRUNCATE TABLE "):
            self.rows[statement.removeprefix("TRUNCATE TABLE ")] = []

    def query(self, statement: str, parameters=None):
        self.queries.append(statement)
        if statement == "SELECT 1 FROM schema_migrations WHERE version = {version:String}":
            return SimpleNamespace(result_rows=[])
        if statement.startswith("SELECT COUNT(*) FROM "):
            table = statement.removeprefix("SELECT COUNT(*) FROM ")
            table = {
                "active_source_records": "dwd_source_records",
                "active_source_record_tags": "dwd_source_record_tags",
                "active_source_daily_stats": "dws_source_daily_stats",
                "active_source_fields": "dws_source_fields",
                "active_source_tag_stats": "dws_source_tag_stats",
            }.get(table, table)
            return SimpleNamespace(result_rows=[(len(self.rows.get(table, [])),)])
        raise AssertionError(statement)

    def insert(self, table: str, rows: list[tuple], column_names: list[str]):
        self.rows.setdefault(table, []).extend(rows)

    def close(self):
        pass


def populated_database(tmp_path: Path) -> Path:
    path = tmp_path / "科技.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at_twitter", "text"])
        writer.writeheader()
        writer.writerow({"created_at_twitter": "2024-01-01", "text": "AI 与半导体"})
        writer.writerow({"created_at_twitter": "2024-01-02", "text": "通胀与加息"})
    database = tmp_path / "catalog.db"
    catalog = CatalogStore(database)
    catalog.import_file(SourceFile.create(tmp_path, path, "social"))
    catalog.close()
    snapshots = SnapshotStore(database)
    snapshots.save("states", [{
        "date": "2024-01-02", "cluster": 1, "label": "趋势上涨 · C1", "confidence": 0.8,
        "model_version": "walk-forward-20240101", "trained_through": "2024-01-01",
        "features": {"market_return": 0.1, "volatility": 0.2, "momentum": 0.3, "correlation": 0.4, "trend": 0.5, "sample_count": 10},
        "contributions": [{"feature": "momentum", "value": 0.3, "standardized": 1.2}],
    }])
    snapshots.save("alerts", [{"date": "2024-01-02", "rule": "HIGH_VOLATILITY", "level": "high", "title": "波动预警", "evidence": "测试证据", "value": 0.2, "threshold": 0.1}])
    snapshots.close()
    return database


def test_schema_and_parameter_contracts():
    statements = sql_statements((Path(__file__).parents[1] / "migrations" / "clickhouse" / "001_analytics.sql").read_text(encoding="utf-8"))
    assert len(statements) == len(ANALYTIC_TABLES)
    assert all("PARTITION BY toYYYYMM(" in statement or "dwd_source_files" in statement or "dws_source_fields" in statement or "dws_source_tag_stats" in statement for statement in statements)
    assert statements[1].count("coalesce(event_date") == 1
    assert statements[2].count("coalesce(event_date") == 1
    params = Parameters()
    assert params.add("2024-01-01", "Date32") == "{p0:Date32}"
    assert params.values == {"p0": "2024-01-01"}
    with pytest.raises(ValueError, match="数据库名"):
        ClickHouseCatalogStore({"database": "bad;database"})


def test_migration_is_repeatable_and_preserves_lineage(tmp_path: Path):
    database = populated_database(tmp_path)
    client = FakeClickHouse()
    store = ClickHouseCatalogStore({"database": "marketlens"}, client=client)
    migrator = ClickHouseMigrator(store, {"volatility_quantile": 0.9})
    catalog = CatalogStore(database)
    try:
        expected = {"files": 1, "records": 2, "tags": 4, "features": 6, "states": 1, "alerts": 1}
        assert migrator.migrate(catalog) == expected
        assert migrator.verify_counts(catalog) == []
        assert migrator.migrate(catalog) == expected
        assert len(client.rows["dwd_source_records"]) == 2
        assert client.rows["dwd_source_records"][0][4] == 1
        assert client.rows["dwd_source_records"][0][-2] == "sqlite-stage-c-v1"
        assert client.rows["dwd_source_records"][0][-1] == 1
        assert client.rows["catalog_publications"][0][:2] == (client.rows["dwd_source_files"][0][0], 1)
        assert client.rows["ads_alerts"][0][2].startswith("rules-")
    finally:
        catalog.close()


def test_empty_overview_and_record_result_contract():
    client = FakeClickHouse()
    store = ClickHouseCatalogStore({"database": "marketlens"}, client=client)
    responses = [
        [(0, 0)], [(None, None, 0)], [], [],
        [(1,)],
        [("source", "科技.csv", "social", 0, date(2024, 1, 1), "标题", '{"text":"正文"}', ["人工智能"])],
    ]
    client.query = lambda statement, parameters=None: SimpleNamespace(result_rows=responses.pop(0))
    empty = store.overview("missing")
    assert empty["records"] == 0
    assert empty["undated_records"] == 0
    result = store.list_records(None, None, None, 0, 20)
    assert result["total"] == 1
    assert result["items"][0]["event_date"] == "2024-01-01"
    assert result["items"][0]["payload"]["text"] == "正文"
    assert result["items"][0]["tags"] == ["人工智能"]
    with pytest.raises(ValueError, match="最多同时筛选 5 个标签"):
        store.list_records(None, None, None, 0, 20, tags=[str(index) for index in range(6)])


def test_insert_blocks_bound_partitions_and_size():
    rows = [(index, date(2000 + index // 12, index % 12 + 1, 1)) for index in range(120)]
    blocks = insert_blocks(rows, ["record_index", "event_date"], max_partitions=50, max_rows=10000)
    assert [len(block) for block in blocks] == [50, 50, 20]
    dense = [(index, date(2024, 1, 1)) for index in range(10001)]
    assert [len(block) for block in insert_blocks(dense, ["record_index", "event_date"])] == [10000, 1]
    undated = [(None, None)]
    assert insert_blocks(undated, ["record_index", "event_date"])[0][0][0] is None


def test_tag_query_uses_scoped_aliases_without_corrupting_tag_filter():
    client = FakeClickHouse()
    store = ClickHouseCatalogStore({"database": "marketlens"}, client=client)
    statements = []
    responses = [
        [(1,)],
        [("source", "科技.csv", "social", 0, date(2024, 1, 1), "标题", '{"text":"正文"}', ["人工智能"])],
    ]

    def query(statement, parameters=None):
        statements.append(statement)
        return SimpleNamespace(result_rows=responses.pop(0))

    client.query = query
    result = store.list_records(None, None, None, 0, 20, tag="人工智能")
    assert result["total"] == 1
    assert "inner_r.source_id AS source_id" in statements[-1]
    assert "inner_r.record_index AS record_index" in statements[-1]
    assert "tag_filter.kind = inner_r.kind" in statements[-1]
    assert "tag_filteinner_r" not in statements[-1]


def test_web_reads_serialize_shared_client_sessions():
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep

    class ConcurrentClient:
        def __init__(self):
            self.active = 0
            self.maximum_active = 0

        def query(self, statement, parameters=None):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            sleep(0.002)
            self.active -= 1
            return SimpleNamespace(result_rows=[])

    client = ConcurrentClient()
    store = ClickHouseCatalogStore({"database": "marketlens"}, client=client)
    with ThreadPoolExecutor(max_workers=12) as executor:
        versions = list(executor.map(lambda _: store.data_version(), range(48)))
    assert len(set(versions)) == 1
    assert client.maximum_active == 1
