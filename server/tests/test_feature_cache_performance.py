from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.system as system_api
from app.core.config import load_config
from app.main import create_app
from app.services.feature_cache_performance import (
    PERFORMANCE_VERSION,
    benchmark_source_sha256,
    load_feature_cache_performance_report,
    performance_report_path,
    source_sha256,
)
from server.benchmarks.feature_cache_performance import measure_reads, summarize_latencies
from server.tests.test_api import fake_service


def valid_report():
    return {
        "report_type": "redis_feature_cache_performance",
        "performance_version": PERFORMANCE_VERSION,
        "source_sha256": source_sha256(),
        "benchmark_source_sha256": benchmark_source_sha256(),
        "measurement": {},
    }


def test_latency_summary_keeps_reference_groups_and_strict_threshold_explicit():
    assert summarize_latencies([], 10)["p95_within_target"] is None
    reference = summarize_latencies([1, 2, 3], None)
    assert reference["target_p95_ms"] is None and reference["p95_within_target"] is None
    assert summarize_latencies([10], 10)["p95_within_target"] is False
    assert summarize_latencies([9.999], 10)["p95_within_target"] is True


def test_production_read_probe_keeps_all_rounds_and_checks_authoritative_value():
    expected = {"date": "2024-01-02", "features": {"volatility": 0.2}}
    ticks = iter([0.0, 0.001, 0.1, 0.102, 0.2, 0.204, 0.3, 0.308])
    result = measure_reads(lambda: dict(expected), expected, 2, 2, clock=lambda: next(ticks))
    assert result["sample_count"] == 4
    assert [item["sample_count"] for item in result["rounds"]] == [2, 2]
    assert result["latency_ms"]["p50"] == 2
    assert result["result_consistent"] is True
    with pytest.raises(AssertionError, match="权威快照"):
        measure_reads(lambda: {"features": {"volatility": 999}}, expected, 1, 1)
    with pytest.raises(ValueError, match="大于 0"):
        measure_reads(lambda: expected, expected, 0, 1)


def test_feature_cache_report_loader_rejects_missing_stale_and_unreadable_reports(tmp_path):
    database = tmp_path / "market.db"
    path = performance_report_path(database)
    with pytest.raises(FileNotFoundError, match="尚未生成"):
        load_feature_cache_performance_report(database)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(valid_report()), encoding="utf-8")
    assert load_feature_cache_performance_report(database)["performance_version"] == PERFORMANCE_VERSION

    stale = valid_report()
    stale["benchmark_source_sha256"] = "stale"
    path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(ValueError, match="不匹配"):
        load_feature_cache_performance_report(database)
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="不可读取"):
        load_feature_cache_performance_report(database)


def test_feature_cache_performance_endpoint_preserves_missing_and_stale_errors():
    service = fake_service()
    service.feature_cache_performance = lambda: valid_report()
    with TestClient(create_app(service, initialize=False)) as http:
        assert http.get("/api/system/feature-cache-performance").status_code == 200
        service.feature_cache_performance = lambda: (_ for _ in ()).throw(FileNotFoundError("尚未生成 Redis 热特征性能报告"))
        missing = http.get("/api/system/feature-cache-performance")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "尚未生成 Redis 热特征性能报告"
        service.feature_cache_performance = lambda: (_ for _ in ()).throw(ValueError("报告与当前运行源码不匹配"))
        assert http.get("/api/system/feature-cache-performance").status_code == 409


def test_feature_cache_performance_uses_bounded_remote_feature_proxy(monkeypatch):
    calls = []

    async def forward(request, url, timeout):
        calls.append((request.url.path, url, timeout))
        return valid_report()

    config = replace(load_config(), feature_service={"url": "http://feature:8002", "timeout_seconds": 2})
    monkeypatch.setattr(system_api, "load_config", lambda: config)
    monkeypatch.setattr(system_api, "forward_feature_request", forward)
    with TestClient(create_app(fake_service(), initialize=False)) as http:
        assert http.get("/api/system/feature-cache-performance").status_code == 200
    assert calls == [("/api/system/feature-cache-performance", "http://feature:8002", 2.0)]
