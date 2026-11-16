from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.api.system as system_api
from app.main import create_app
from app.services.page_performance import PERFORMANCE_VERSION, load_page_performance_report, performance_report_path, source_sha256
from server.benchmarks.page_performance import summarize_mode, summarize_samples
from server.tests.test_api import fake_service


def valid_report():
    return {
        "report_type": "browser_page_performance",
        "performance_version": PERFORMANCE_VERSION,
        "source_sha256": source_sha256(),
        "measurement": {},
    }


def sample(mode="cold_empty_context", page="overview", ready=100, success=True):
    return {"mode": mode, "page": page, "ready_ms": ready, "success": success}


def test_latency_summary_does_not_hide_failed_or_empty_samples():
    result = summarize_samples([sample(ready=100), sample(ready=2000), sample(ready=300, success=False)], 2000)
    assert result["attempt_count"] == 3
    assert result["successful_count"] == 2
    assert result["failed_count"] == 1
    assert result["sample_count"] == 2
    assert result["p95_within_target"] is False
    assert summarize_samples([], 2000)["p95_within_target"] is None
    assert summarize_samples([sample(ready=1999)], 2000)["p95_within_target"] is True
    reference = summarize_samples([sample(ready=3000)], None)
    assert reference["target_p95_ms"] is None and reference["p95_within_target"] is None


def test_mode_summary_keeps_page_boundaries():
    routes = [{"id": "overview"}, {"id": "system"}]
    samples = [sample(page="overview", ready=100), sample(page="system", ready=300)]
    result = summarize_mode(samples, routes, "cold_empty_context", 2000)
    assert result["attempt_count"] == 2
    assert result["by_page"]["overview"]["latency_ms"]["p95"] == 100
    assert result["by_page"]["system"]["latency_ms"]["p95"] == 300


def test_page_report_loader_rejects_missing_stale_and_unreadable_reports(tmp_path):
    database = tmp_path / "market.db"
    path = performance_report_path(database)
    with pytest.raises(FileNotFoundError, match="尚未生成"):
        load_page_performance_report(database)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(valid_report()), encoding="utf-8")
    assert load_page_performance_report(database)["performance_version"] == PERFORMANCE_VERSION
    stale = valid_report()
    stale["source_sha256"]["web/src/App.tsx"] = "stale"
    path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(ValueError, match="不匹配"):
        load_page_performance_report(database)
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="不可读取"):
        load_page_performance_report(database)


def test_page_performance_endpoint_preserves_missing_and_stale_errors(monkeypatch):
    monkeypatch.setattr(system_api, "load_page_performance_report", lambda _: valid_report())
    with TestClient(create_app(fake_service(), initialize=False)) as http:
        assert http.get("/api/system/page-performance").status_code == 200
    monkeypatch.setattr(system_api, "load_page_performance_report", lambda _: (_ for _ in ()).throw(FileNotFoundError("尚未生成页面加载性能报告")))
    with TestClient(create_app(fake_service(), initialize=False)) as http:
        assert http.get("/api/system/page-performance").status_code == 404
    monkeypatch.setattr(system_api, "load_page_performance_report", lambda _: (_ for _ in ()).throw(ValueError("报告与当前源码不匹配")))
    with TestClient(create_app(fake_service(), initialize=False)) as http:
        assert http.get("/api/system/page-performance").status_code == 409
