from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.core.config import load_config
from app.services.catalog import CatalogStore
from app.services.clickhouse_store import ClickHouseCatalogStore
from app.services.market import MarketService
from app.services.online_publish import OnlinePublisher
from app.services.storage import SnapshotStore
from market_core.domain.sources import SourceFile


class FakeOnlineStore:
    def __init__(self):
        self.rows = {}
        self.versions = {}
        self.runs = []
        self.discarded = []

    def initialize(self):
        return []

    def published_versions(self):
        return self.versions

    def insert(self, table, rows, columns):
        self.rows.setdefault(table, []).extend(rows)

    def discard_staged(self, source_id, generation):
        if source_id in self.versions:
            assert generation != self.versions[source_id][2]
        self.discarded.append((source_id, generation))

    def record_run(self, source_id, generation, status, record_count=0, error=None):
        self.runs.append((source_id, generation, status, error))

    def activate(self, source_id, generation, record_count):
        file_row = next(row for row in self.rows["dwd_source_files"] if row[0] == source_id and row[-1] == generation)
        self.versions[source_id] = (file_row[3], file_row[4], generation)
        self.record_run(source_id, generation, "published", record_count)


def source_and_catalog(tmp_path: Path) -> tuple[SourceFile, CatalogStore]:
    path = tmp_path / "科技.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at_twitter", "text"])
        writer.writeheader()
        writer.writerow({"created_at_twitter": "2024-01-01", "text": "AI 与半导体"})
    source = SourceFile.create(tmp_path, path, "social")
    catalog = CatalogStore(tmp_path / "catalog.db")
    catalog.import_file(source)
    snapshots = SnapshotStore(tmp_path / "catalog.db")
    snapshots.save("states", [])
    snapshots.save("alerts", [])
    snapshots.close()
    return source, catalog


def publisher(catalog: CatalogStore, store: FakeOnlineStore) -> OnlinePublisher:
    result = OnlinePublisher(catalog, store)
    result.migrator.refresh_market = lambda current: {"states": 0, "alerts": 0}
    result.migrator.verify_counts = lambda current: []
    result.migrator.verify_queries = lambda current: []
    result._verify_staged = lambda source, generation: None
    return result


def test_republish_uses_new_generation_and_unchanged_sources_are_skipped(tmp_path: Path):
    source, catalog = source_and_catalog(tmp_path)
    store = FakeOnlineStore()
    try:
        online = publisher(catalog, store)
        assert online.publish([source])["published"] == 1
        first_generation = store.versions[source.id][2]
        assert online.publish([source])["skipped"] == 1
        assert len(store.discarded) == 1
        assert online.publish([source], only_changed=False)["published"] == 1
        assert store.versions[source.id][2] > first_generation
        assert store.discarded[-1][1] == store.versions[source.id][2]
        assert store.runs[-1][2] == "published"
    finally:
        catalog.close()


def test_failed_staging_keeps_the_active_generation(tmp_path: Path):
    source, catalog = source_and_catalog(tmp_path)
    store = FakeOnlineStore()
    try:
        online = publisher(catalog, store)
        online.publish([source])
        active = store.versions[source.id]

        def reject_staging(selected_source, generation):
            raise ValueError("模拟内容差异")

        online._verify_staged = reject_staging
        with pytest.raises(ValueError, match="模拟内容差异"):
            online.publish([source], only_changed=False)
        assert store.versions[source.id] == active
        assert store.runs[-1][2] == "failed"
    finally:
        catalog.close()


def test_online_views_read_only_the_latest_publication():
    script = (Path(__file__).parents[1] / "migrations" / "clickhouse" / "002_online_publications.sql").read_text(encoding="utf-8")
    assert script.count("catalog_publications AS p FINAL") == 6
    assert script.count("ADD COLUMN IF NOT EXISTS generation") == 6


def test_explicit_distributed_config_selects_clickhouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw = json.loads((Path(__file__).parents[1] / "config.example.json").read_text(encoding="utf-8"))
    raw["data_root"] = "../data"
    raw["database_path"] = "catalog.db"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("STORAGE_MODE", "distributed")
    monkeypatch.setenv("CLICKHOUSE_ENABLED", "true")
    monkeypatch.setenv("CLICKHOUSE_HOST", "clickhouse")
    config = load_config(path)
    service = MarketService(config)
    try:
        assert config.clickhouse["host"] == "clickhouse"
        assert isinstance(service.catalog, ClickHouseCatalogStore)
    finally:
        service.close()
    monkeypatch.setenv("CLICKHOUSE_ENABLED", "false")
    with pytest.raises(ValueError, match="distributed"):
        load_config(path)
