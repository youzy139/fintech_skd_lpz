from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.data_service import create_data_app
from app.main import create_app
from app.services.cache import CachedCatalogStore, RedisJsonCache
from app.services.clickhouse_store import ClickHouseCatalogStore
from app.services.data_catalog import DataCatalogService
from app.services.remote_catalog import DataServiceError, RemoteCatalogClient
from app.services.remote_feature import RemoteFeatureService
from app.services.source_governance import file_governance_report
from market_core.domain.sources import SourceFile
from test_api import fake_service
from test_cache import FakeRedis
from test_data_service import FakeResponse
from test_source_governance import catalog


def source_id(catalog):
    return catalog.list_files(None, None, 0, 20)["items"][0]["id"]


def test_file_report_is_scoped_and_uses_only_preaggregated_evidence(catalog, tmp_path):
    identifier = source_id(catalog)
    path = tmp_path / "another.csv"
    path.write_text("created_at_twitter,text\n2024-02-02,other\n", encoding="utf-8")
    catalog.import_file(SourceFile.create(tmp_path, path, "social"))
    calls = []
    catalog.connection.set_trace_callback(calls.append)
    report = catalog.file_governance(identifier)
    assert report["scope"] == "source-file"
    assert report["file"]["path"] == "social.csv"
    assert "error" not in report["file"]
    assert report["records"] == 3 and report["dated_records"] == 1
    assert report["start_date"] == report["end_date"] == "2024-01-01"
    assert report["undated_ratio"] == pytest.approx(2 / 3)
    assert report["statistics_status"] == "consistent"
    assert report["fields"][0]["empty_or_absent_count"] == 1
    assert report["fields"][0]["empty_or_absent_ratio"] == pytest.approx(1 / 3)
    assert report["duplicate_records"] is report["invalid_records"] is None
    assert all("source_records" not in sql for sql in calls)
    assert all(sql.startswith("SELECT ") for sql in calls)
    assert catalog.file_governance("' OR 1=1 --") is None


@pytest.mark.parametrize("corruption", ["UPDATE source_fields SET non_null_count=4", "UPDATE source_daily_stats SET record_count=4"])
def test_inconsistent_statistics_disable_all_ratios(catalog, corruption):
    catalog.connection.execute(corruption)
    report = catalog.file_governance(source_id(catalog))
    assert report["statistics_status"] == "inconsistent"
    assert report["undated_ratio"] is None
    assert all(field["empty_or_absent_count"] is field["empty_or_absent_ratio"] is None for field in report["fields"])


def test_failed_import_and_empty_file_do_not_invent_percentages(catalog):
    identifier = source_id(catalog)
    catalog.connection.execute("UPDATE source_files SET status='failed'")
    report = catalog.file_governance(identifier)
    assert report["statistics_status"] == "unavailable"
    assert report["undated_ratio"] is None
    catalog.connection.execute("UPDATE source_files SET status='imported', record_count=0")
    catalog.connection.execute("DELETE FROM source_daily_stats")
    catalog.connection.execute("DELETE FROM source_fields")
    report = catalog.file_governance(identifier)
    assert report["statistics_status"] == "consistent"
    assert report["fields"] == [] and report["start_date"] is None
    assert report["undated_records"] == 0 and report["undated_ratio"] is None


def test_fields_are_bounded_and_quality_reports_bypass_cache(catalog):
    identifier = source_id(catalog)
    catalog.connection.executemany(
        "INSERT INTO source_fields VALUES (?, ?, ?, ?)",
        [(identifier, f"field_{i}", i + 2, 1) for i in range(100)],
    )
    cached = CachedCatalogStore(catalog, RedisJsonCache(FakeRedis(), "test", 60))
    report = cached.file_governance(identifier)
    assert len(report["fields"]) == 100 and report["fields_truncated"] is True
    catalog.connection.execute("UPDATE source_daily_stats SET record_count=2")
    assert cached.file_governance(identifier)["undated_records"] == 1
    assert cached.cache_stats["writes"] == 0


@pytest.mark.parametrize("present", [True, False])
def test_version_change_rejects_reports_even_for_missing_files(catalog, present):
    versions = iter(["a", "b"])
    reader = SimpleNamespace(data_version=lambda: next(versions), _file_statistics=catalog._file_statistics)
    with pytest.raises(DataServiceError):
        file_governance_report(reader, source_id(catalog) if present else "missing")


@pytest.mark.parametrize("entrypoint", ["main", "data"])
def test_file_report_works_in_main_and_data_service(catalog, entrypoint):
    service = DataCatalogService(load_config(), catalog)
    if entrypoint == "data":
        app = create_data_app(service)
    else:
        market = fake_service()
        market.source_file_governance = service.source_file_governance
        app = create_app(market, initialize=False)
    with TestClient(app) as client:
        result = client.get(f"/api/data/files/{source_id(catalog)}/governance")
        assert result.status_code == 200
        assert result.json() == catalog.file_governance(source_id(catalog))
        missing = client.get("/api/data/files/unknown/governance")
        assert missing.status_code == 404 and missing.json()["error"]["request_id"]
        def unavailable(_):
            raise DataServiceError("private host")
        app.state.service.source_file_governance = unavailable
        failed = client.get("/api/data/files/unknown/governance")
        assert failed.status_code == 503 and failed.headers["Retry-After"] == "5"
        assert "private" not in failed.text


def test_remote_file_report_preserves_path_timeout_and_error_semantics(catalog):
    expected = catalog.file_governance(source_id(catalog))
    calls = []
    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse(expected)
    reader = RemoteCatalogClient("http://data-service:8000", 2.5, opener)
    remote = object.__new__(RemoteFeatureService)
    remote.catalog = reader
    assert remote.source_file_governance("id with space") == expected
    assert calls == [("http://data-service:8000/api/data/files/id%20with%20space/governance", 2.5)]
    def missing(*args, **kwargs):
        raise HTTPError("http://private", 404, "missing", {}, None)
    reader.opener = missing
    assert reader.file_governance("missing") is None
    with pytest.raises(DataServiceError):
        reader.summary()
    def unavailable(*args, **kwargs):
        raise URLError("private host")
    reader.opener = unavailable
    with pytest.raises(DataServiceError):
        reader.file_governance("id")


def test_clickhouse_file_evidence_uses_parameterized_active_views():
    calls = []
    responses = iter([
        [("id", 1, 3)],
        [("id", "social", "social.csv", "imported", 3, 0, "[]", 50, 123)],
        [(date(2024, 1, 1), date(2024, 1, 1), 1)], [("text", 2)], [("id", 1, 3)],
    ])
    def query(sql, parameters=None):
        calls.append((sql, parameters))
        return SimpleNamespace(result_rows=next(responses))
    reader = ClickHouseCatalogStore({"database": "test"}, SimpleNamespace(query=query))
    report = reader.file_governance("id'quoted")
    assert report["undated_records"] == 2 and report["fields"][0]["empty_or_absent_count"] == 1
    assert report["audit_registration"]["status"] == "not_comparable"
    assert all(sql.startswith("SELECT ") and "id'quoted" not in sql for sql, _ in calls)
    assert "minOrNull" in calls[2][0]
    assert "LIMIT 101" in calls[3][0]
    assert all("source_records" not in sql for sql, _ in calls)
