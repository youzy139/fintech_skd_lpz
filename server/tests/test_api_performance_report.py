from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.api.system as system_api
from app.main import create_app
from app.services.api_performance import PERFORMANCE_VERSION, performance_report_path, source_sha256
from app.services.api_performance import load_api_performance_report
from test_api import fake_service


def valid_report():
    return {
        "report_type": "independent_user_api_performance",
        "performance_version": PERFORMANCE_VERSION,
        "source_sha256": source_sha256(),
        "measurement": {},
    }


def test_api_performance_report_loads_only_matching_source(tmp_path):
    database = tmp_path / "market.db"
    path = performance_report_path(database)
    path.parent.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="尚未生成"):
        load_api_performance_report(database)
    path.write_text(json.dumps(valid_report()), encoding="utf-8")
    assert load_api_performance_report(database)["performance_version"] == PERFORMANCE_VERSION
    stale = valid_report()
    stale["source_sha256"]["server/app/core/auth.py"] = "stale"
    path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(ValueError, match="源码不匹配"):
        load_api_performance_report(database)


def test_api_performance_endpoint_keeps_missing_and_stale_errors(monkeypatch):
    monkeypatch.setattr(system_api, "load_api_performance_report", lambda _: valid_report())
    with TestClient(create_app(fake_service(), initialize=False)) as http:
        assert http.get("/api/system/api-performance").status_code == 200
    monkeypatch.setattr(system_api, "load_api_performance_report", lambda _: (_ for _ in ()).throw(FileNotFoundError("尚未生成独立用户 API 性能报告")))
    with TestClient(create_app(fake_service(), initialize=False)) as http:
        assert http.get("/api/system/api-performance").status_code == 404
    monkeypatch.setattr(system_api, "load_api_performance_report", lambda _: (_ for _ in ()).throw(ValueError("报告与当前运行源码不匹配")))
    with TestClient(create_app(fake_service(), initialize=False)) as http:
        assert http.get("/api/system/api-performance").status_code == 409
