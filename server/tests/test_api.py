from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from market_core.domain.market import AssetMeta, AssetSeries
from app.main import create_app
from app.services.remote_catalog import DataServiceError


def fake_service():
    meta = AssetMeta("权益", "测试指数", "TEST", "close", "测试", date(2024, 1, 1), date(2024, 1, 2), 2, Path("test.csv"))
    series = AssetSeries(meta, pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-01-02"]), "value": [100, 102]}))
    state = {"date": "2024-01-02", "label": "趋势上涨", "confidence": 0.8, "model_version": "test", "features": {"volatility": 0.2}, "contributions": []}
    helper = MarketServiceAssets([series])
    return SimpleNamespace(
        series=[series], states=[state], alerts=[{"date": "2024-01-02", "rule": "TEST", "level": "low"}],
        quality={"loaded_assets": 1, "total_rows": 2}, assets=helper.assets, latest_state=lambda: state,
        asset_series=helper.asset_series,
        feature_metadata=lambda: {"feature_contract": {"feature_version": "test-features"}, "input_version": "test-input"},
        latest_features=lambda: {name: state[name] for name in ("date", "features", "contributions", "model_version")},
        stability_evaluation=lambda: {"report_type": "regime_stability", "evaluation_version": "stability-v1", "runs": []},
        computation_performance=lambda: {"report_type": "model_computation_performance", "performance_version": "model-computation-performance-v1", "summary": {}},
        feature_cache_performance=lambda: {"report_type": "redis_feature_cache_performance", "performance_version": "redis-feature-cache-performance-v1", "measurement": {}},
        research_case=lambda: {"case_version": "research-case-v1", "case_id": "case-test", "is_financial_event_label": False},
        feature_cache_status=lambda: {"enabled": False, "view": "current-market"},
        home_summary=lambda: {"latest": state, "alert_count": 1, "loaded_assets": 1, "total_rows": 2, "state_count": 1},
        health_details=lambda: {"storage_mode": "local", "assets": 1, "states": 1},
        market_readiness=lambda: {"status": "ok", "assets": 1, "states": 1},
        replay_metrics=lambda: {"replay_sessions": 0, "active_replays": 0},
        data_version=lambda: "version-1",
        source_summary=lambda: {"total_files": 1, "imported_files": 1, "total_records": 2, "errors": 0, "groups": []},
        source_governance=lambda kind: {"kind": kind, "items": [], "scope": "source-kind"},
        source_file_governance=lambda source_id: None,
        source_overview=lambda kind: {"kind": kind, "files": 1, "records": 2, "start_date": "2024-01-01", "end_date": "2024-01-02", "undated_records": 0, "granularity": "day", "trend": [{"period": "2024-01-02", "count": 2}], "fields": []},
        source_tags=lambda kind: [{"tag": "人工智能", "records": 1}],
        source_files=lambda kind, query, offset, limit: {"total": 1, "items": [{"id": "source", "path": "科技.csv", "status": "imported", "record_count": 2}]},
        source_records=lambda source_id, query, date, offset, limit, kind=None, tag=None, tags=None, match="any": {"total": 1, "offset": offset, "limit": limit, "items": [{"source_id": "source", "source_path": "科技.csv", "kind": "social", "record_index": 0, "event_date": "2024-01-02", "title": "测试记录", "payload": {"text": "<b>原文</b>"}, "tags": ["人工智能"]}]},
    )


class MarketServiceAssets:
    def __init__(self, series):
        self.series = series

    def assets(self):
        return [{"code": item.meta.code, "name": item.meta.name} for item in self.series]

    def asset_series(self, code, limit):
        item = next((entry for entry in self.series if entry.meta.code == code), None)
        if item is None:
            raise KeyError(code)
        return {"code": code, "points": [{"date": day.strftime("%Y-%m-%d"), "value": value} for day, value in zip(item.frame["date"], item.frame["value"])]}


def client():
    return TestClient(create_app(fake_service(), initialize=False))


def test_rest_and_graphql_return_real_service_data():
    with client() as http:
        assert http.get("/api/health").json()["assets"] == 1
        assert http.get("/api/assets/TEST/series").json()["points"][1]["value"] == 102
        response = http.post("/graphql", json={"query": "{ latestState }"})
        assert response.status_code == 200
        assert response.json()["data"]["latestState"]["label"] == "趋势上涨"


def test_home_summary_is_small_and_complete():
    with client() as http:
        summary = http.get("/api/home/summary").json()
        assert summary["latest"]["label"] == "趋势上涨"
        assert summary["alert_count"] == 1
        assert summary["total_rows"] == 2
        assert "states" not in summary
        assert "alerts" not in summary


def test_stability_report_uses_read_only_service_and_stable_errors():
    service = fake_service()
    with TestClient(create_app(service, initialize=False)) as http:
        assert http.get("/api/regimes/evaluation/stability").json()["evaluation_version"] == "stability-v1"
        service.stability_evaluation = lambda: (_ for _ in ()).throw(FileNotFoundError("尚未生成模型稳定性报告，请先运行只读评估脚本"))
        missing = http.get("/api/regimes/evaluation/stability")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        service.stability_evaluation = lambda: (_ for _ in ()).throw(ValueError("稳定性报告与当前输入、特征或模型配置不匹配，请重新生成"))
        stale = http.get("/api/regimes/evaluation/stability")
        assert stale.status_code == 409
        assert stale.json()["detail"].startswith("稳定性报告与当前输入")


def test_computation_performance_report_has_stable_missing_and_stale_errors():
    service = fake_service()
    with TestClient(create_app(service, initialize=False)) as http:
        assert http.get("/api/system/computation-performance").json()["performance_version"] == "model-computation-performance-v1"
        service.computation_performance = lambda: (_ for _ in ()).throw(FileNotFoundError("尚未生成单日计算性能报告，请先运行只读基准脚本"))
        assert http.get("/api/system/computation-performance").status_code == 404
        service.computation_performance = lambda: (_ for _ in ()).throw(ValueError("单日计算性能报告与当前输入、特征、模型或计算源码不匹配，请重新生成"))
        assert http.get("/api/system/computation-performance").status_code == 409


def test_latest_research_case_has_stable_not_found_contract():
    service = fake_service()
    with TestClient(create_app(service, initialize=False)) as http:
        response = http.get("/api/research/cases/latest")
        assert response.status_code == 200
        assert response.json()["case_id"] == "case-test"
        assert response.json()["is_financial_event_label"] is False
        service.research_case = lambda: (_ for _ in ()).throw(KeyError("当前没有可用于研究案例的历史预警"))
        missing = http.get("/api/research/cases/latest")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "当前没有可用于研究案例的历史预警"
        assert missing.json()["error"]["code"] == "not_found"


def test_websocket_replay_has_event_time():
    with client() as http:
        with http.websocket_connect("/ws/replay?max_messages=1") as websocket:
            message = websocket.receive_json()
            assert message["event_time"] == "2024-01-02"
            assert websocket.receive_json()["type"] == "replay_complete"


def test_source_catalog_and_graphql_summary():
    with client() as http:
        assert http.get("/api/data/summary").json()["total_records"] == 2
        assert http.get("/api/data/overview?kind=social").json()["trend"][0]["count"] == 2
        assert http.get("/api/data/tags?kind=social").json()[0]["tag"] == "人工智能"
        assert http.get("/api/data/files?kind=social").json()["items"][0]["path"] == "科技.csv"
        assert http.get("/api/data/files/source/records").json()["items"][0]["payload"]["text"] == "<b>原文</b>"
        page = http.get("/api/data/records?kind=social&offset=0&limit=20")
        assert page.status_code == 200
        assert page.json()["items"][0]["source_path"] == "科技.csv"
        assert http.get("/api/data/records?offset=-1").status_code == 422
        assert http.get("/api/data/records?limit=101").status_code == 422
        assert http.get("/api/data/records?tags=人工智能&tags=半导体&match=all").status_code == 200
        assert http.get("/api/data/records?match=invalid").status_code == 422
        assert http.get("/api/data/records?tags=1&tags=2&tags=3&tags=4&tags=5&tags=6").status_code == 422
        response = http.post("/graphql", json={"query": "{ sourceSummary }"})
        assert response.json()["data"]["sourceSummary"]["imported_files"] == 1


def test_request_ids_error_contract_readiness_and_metrics():
    with client() as http:
        health = http.get("/api/health", headers={"X-Request-ID": "trace.test-1"})
        assert health.headers["X-Request-ID"] == "trace.test-1"
        missing = http.get("/api/assets/missing/series")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "资产不存在"
        assert missing.json()["error"]["code"] == "not_found"
        assert missing.json()["error"]["request_id"] == missing.headers["X-Request-ID"]
        invalid = http.get("/api/data/records?limit=0")
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation_error"
        ready = http.get("/api/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"]["catalog"]["records"] == 2
        metrics = http.get("/api/system/metrics").json()
        assert metrics["scope"] == "process"
        assert metrics["request_count"] >= 4
        health_metrics = next(item for item in metrics["routes"] if item["route"] == "/api/health")
        assert health_metrics["p50_ms"] >= 0
        assert health_metrics["p95_ms"] >= health_metrics["p50_ms"]


def test_internal_errors_do_not_leak_implementation_details():
    service = fake_service()

    def fail_summary():
        raise RuntimeError("private implementation detail")
    service.source_summary = fail_summary
    with TestClient(create_app(service, initialize=False), raise_server_exceptions=False) as http:
        response = http.get("/api/data/summary")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "private implementation detail" not in response.text
        assert http.get("/api/health/ready").status_code == 503


def test_data_service_failure_uses_stable_retryable_error():
    service = fake_service()

    def fail_summary():
        raise DataServiceError("private upstream detail")
    service.source_summary = fail_summary
    with TestClient(create_app(service, initialize=False)) as http:
        assert http.get("/api/data/version").json() == {"data_version": "version-1"}
        response = http.get("/api/data/summary", headers={"X-Request-ID": "trace.upstream-1"})
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        assert response.json()["error"] == {"code": "data_service_unavailable", "message": "数据服务暂时不可用", "request_id": "trace.upstream-1"}
        assert "private upstream detail" not in response.text


def test_catalog_fast_path_returns_current_cached_values_without_worker_fallback():
    service = fake_service()
    summary = {"total_files": 1, "cached": True}
    records = {"total": 1, "items": [{"title": "cached"}]}
    service.catalog = SimpleNamespace(
        try_local_summary=lambda: (True, summary),
        try_local_records=lambda *args: (True, records),
    )

    def unexpected_worker_call(*args, **kwargs):
        raise AssertionError("立即缓存命中不应回退到工作线程")

    service.source_summary = unexpected_worker_call
    service.source_records = unexpected_worker_call
    with TestClient(create_app(service, initialize=False)) as http:
        assert http.get("/api/data/summary").json() == summary
        assert http.get("/api/data/records").json() == records
        assert http.get("/api/data/files/source/records").json() == records
