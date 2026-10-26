from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from market_core.domain.market import AssetMeta, AssetSeries
from app.main import create_app


def fake_service():
    meta = AssetMeta("权益", "测试指数", "TEST", "close", "测试", date(2024, 1, 1), date(2024, 1, 2), 2, Path("test.csv"))
    series = AssetSeries(meta, pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-01-02"]), "value": [100, 102]}))
    state = {"date": "2024-01-02", "label": "趋势上涨", "confidence": 0.8, "model_version": "test", "features": {"volatility": 0.2}, "contributions": []}
    helper = MarketServiceAssets([series])
    return SimpleNamespace(series=[series], states=[state], alerts=[{"date": "2024-01-02", "rule": "TEST", "level": "low"}], quality={"loaded_assets": 1}, assets=helper.assets, latest_state=lambda: state, asset_series=helper.asset_series, source_summary=lambda: {"total_files": 1, "imported_files": 1, "total_records": 2, "errors": 0, "groups": []}, source_files=lambda kind, query, offset, limit: {"total": 1, "items": [{"id": "source", "path": "科技.csv", "status": "imported", "record_count": 2}]}, source_records=lambda source_id, query, date, offset, limit: {"total": 1, "items": [{"record_index": 0, "title": "测试记录", "payload": {"text": "<b>原文</b>"}}]})


class MarketServiceAssets:
    def __init__(self, series):
        self.series = series

    def assets(self):
        return [{"code": item.meta.code, "name": item.meta.name} for item in self.series]

    def asset_series(self, code, limit):
        item = self.series[0]
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


def test_websocket_replay_has_event_time():
    with client() as http:
        with http.websocket_connect("/ws/replay?max_messages=1") as websocket:
            message = websocket.receive_json()
            assert message["event_time"] == "2024-01-02"
            assert websocket.receive_json()["type"] == "replay_complete"


def test_source_catalog_and_graphql_summary():
    with client() as http:
        assert http.get("/api/data/summary").json()["total_records"] == 2
        assert http.get("/api/data/files?kind=social").json()["items"][0]["path"] == "科技.csv"
        assert http.get("/api/data/files/source/records").json()["items"][0]["payload"]["text"] == "<b>原文</b>"
        response = http.post("/graphql", json={"query": "{ sourceSummary }"})
        assert response.json()["data"]["sourceSummary"]["imported_files"] == 1
