from __future__ import annotations

import csv
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.data_service import create_data_app
from app.main import create_app
from app.services.cache import CachedCatalogStore, RedisJsonCache
from app.services.catalog import CatalogStore
from app.services.clickhouse_store import ClickHouseCatalogStore
from app.services.data_catalog import DataCatalogService
from app.services.remote_catalog import DataServiceError, RemoteCatalogClient
from app.services.remote_feature import RemoteFeatureService
from app.services.source_governance import governance_report
from market_core.domain.source_governance import source_policy
from market_core.domain.sources import SourceFile
from test_api import fake_service
from test_cache import FakeRedis
from test_data_service import FakeResponse


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "social.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows([
            ["created_at_twitter", "text"], ["2024-01-01", "one"],
            ["2024-99-99", ""], ["", "three"],
        ])
    store = CatalogStore(tmp_path / "catalog.db")
    store.import_file(SourceFile.create(tmp_path, path, "social"))
    yield store
    store.close()


def test_governance_uses_real_ingestion_counts_without_rewriting(catalog):
    before = catalog.list_records(None, None, None, 0, 20)
    item = catalog.governance("social")["items"][0]
    assert item["records"] == 3
    assert item["undated_records"] == 2
    assert item["undated_ratio"] == pytest.approx(2 / 3)
    assert item["start_date"] == item["end_date"] == "2024-01-01"
    assert {field["name"]: field["non_null_count"] for field in item["fields"]} == {"created_at_twitter": 2, "text": 2}
    assert item["duplicate_records"] is None and item["invalid_records"] is None
    assert catalog.list_records(None, None, None, 0, 20) == before


def test_policies_cover_empty_sources_and_keep_unreviewed_data_out(catalog):
    report = catalog.governance(None)
    items = {item["kind"]: item for item in report["items"]}
    assert len(items) == 8
    assert items["asset"]["usage"] == "model"
    assert items["calendar"]["usage"] == items["publication"]["usage"] == "background"
    for kind in ("news", "indicator", "commodity", "research", "social"):
        assert items[kind]["usage"] == "catalog_only"
    assert items["news"]["records"] == 0
    assert items["news"]["undated_ratio"] is None
    for item in items.values():
        assert item["lifecycle"]["automatic_delete"] is False
        assert item["lifecycle"]["retention_days"] is None
    items["asset"]["lifecycle"]["automatic_delete"] = True
    assert source_policy("asset")["lifecycle"]["automatic_delete"] is False
    assert source_policy("unknown")["usage"] == "catalog_only"


def test_changed_version_rejects_mixed_report(catalog):
    versions = iter(["before", "after"])
    reader = SimpleNamespace(data_version=lambda: next(versions), summary=catalog.summary, overview=catalog.overview)
    with pytest.raises(DataServiceError):
        governance_report(reader, "social")


def test_inconsistent_statistics_do_not_produce_false_ratio(catalog):
    catalog.connection.execute("UPDATE source_daily_stats SET record_count=20")
    item = catalog.governance("social")["items"][0]
    assert item["statistics_status"] == "inconsistent"
    assert item["undated_records"] == -17
    assert item["undated_ratio"] is None


def test_governance_refreshes_through_catalog_cache(catalog):
    cached = CachedCatalogStore(catalog, RedisJsonCache(FakeRedis(), "test", 60))
    assert cached.governance("social")["items"][0]["undated_records"] == 2
    catalog.connection.execute("UPDATE source_daily_stats SET record_count=2")
    assert cached.governance("social")["items"][0]["undated_records"] == 1
    assert cached.cache_stats["writes"] == 0


@pytest.mark.parametrize("entrypoint", ["data", "main"])
def test_real_catalog_report_at_both_entrypoints(catalog, entrypoint):
    service = DataCatalogService(load_config(), catalog)
    if entrypoint == "data":
        app = create_data_app(service)
    else:
        market = fake_service()
        market.source_governance = service.source_governance
        app = create_app(market, initialize=False)
    with TestClient(app) as http:
        response = http.get("/api/data/governance?kind=social")
        assert response.status_code == 200
        assert response.json() == catalog.governance("social")
        assert http.get("/api/data/governance?kind=unknown").status_code == 422
        assert http.post("/api/data/governance").status_code == 405


def test_remote_catalog_preserves_report_filter_and_timeout(catalog):
    expected = catalog.governance("social")
    calls = []
    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(expected)
    reader = RemoteCatalogClient("http://data-service:8000", 2.5, opener)
    remote = object.__new__(RemoteFeatureService)
    remote.catalog = reader
    assert remote.source_governance("social") == expected
    assert calls[0][0].full_url == "http://data-service:8000/api/data/governance?kind=social"
    assert calls[0][1] == 2.5


def test_clickhouse_governance_only_reads_active_statistics():
    calls = []
    responses = iter([
        [("id", 1, 3)], [(1, 1, 3, 0)], [("social", 1, 3)],
        [(1, 3)], [(date(2024, 1, 1), date(2024, 1, 1), 1)],
        [("2024-01-01", 1)], [("text", 0, 2)], [("id", 1, 3)],
    ])
    def query(sql, parameters=None):
        calls.append(sql)
        return SimpleNamespace(result_rows=next(responses))
    catalog = ClickHouseCatalogStore({"database": "test"}, SimpleNamespace(query=query))
    report = catalog.governance("social")
    assert report["items"][0]["undated_records"] == 2
    assert all(sql.startswith("SELECT ") for sql in calls)
    assert any("active_source_fields" in sql for sql in calls)


def test_unavailable_report_returns_stable_error(catalog):
    service = DataCatalogService(load_config(), catalog)
    def unavailable(_):
        raise DataServiceError("private host and database detail")
    service.source_governance = unavailable
    with TestClient(create_data_app(service)) as http:
        response = http.get("/api/data/governance")
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        assert response.json()["error"]["request_id"]
        assert "private" not in response.text
