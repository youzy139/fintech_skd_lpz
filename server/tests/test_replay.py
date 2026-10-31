from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.replay import ReplayDataCatalog
from market_core.domain.market import AssetMeta, AssetSeries
from market_core.domain.replay import ReplayClock
from market_core.models.features import build_market_features
from market_core.models.regime import WalkForwardRegimeModel
from market_core.models.replay import HistoricalMarketReplay


MODEL_SETTINGS = {
    "analysis_start": "2024-01-01",
    "minimum_history": 5,
    "training_window": 10,
    "refit_interval": 3,
    "volatility_window": 3,
    "momentum_window": 20,
    "cluster_count": 2,
    "random_seed": 42,
}
ALERT_SETTINGS = {"volatility_quantile": 0.9, "correlation_quantile": 0.9}


def sample_series(days: int = 80) -> list[AssetSeries]:
    dates = pd.bdate_range("2024-01-01", periods=days)
    result = []
    for code, values in (("A", np.linspace(100, 150, days) + np.sin(np.arange(days))), ("B", np.linspace(80, 110, days) + np.cos(np.arange(days)))):
        meta = AssetMeta("测试", code, code, "close", "测试", dates[0].date(), dates[-1].date(), days, Path(f"{code}.csv"))
        result.append(AssetSeries(meta, pd.DataFrame({"date": dates, "value": values})))
    return result


def test_clock_controls_and_rejects_invalid_transitions():
    clock = ReplayClock((date(2024, 1, 1), date(2024, 1, 2)))
    with pytest.raises(ValueError):
        clock.pause()
    clock.start()
    clock.pause()
    assert clock.status == "paused"
    with pytest.raises(ValueError):
        clock.advance()
    clock.resume()
    clock.set_speed(5)
    assert clock.advance() == date(2024, 1, 1)
    assert clock.current_date == date(2024, 1, 1)
    assert clock.advance() == date(2024, 1, 2)
    assert clock.status == "running"
    clock.complete()
    assert clock.status == "completed"
    clock.restart()
    assert clock.status == "pending"
    assert clock.position == 0
    with pytest.raises(ValueError):
        ReplayClock((date(2024, 1, 1),), speed=3)


def test_daily_input_uses_only_the_requested_event_date():
    catalog = ReplayDataCatalog(sample_series())
    day = catalog.dates[30]
    batch = catalog.read(day)
    assert batch.observations
    assert {item.event_date for item in batch.observations} == {day}
    assert {item.code for item in batch.observations} == {"A", "B"}
    assert catalog.read(date(2024, 1, 6)).observations == ()


def test_replay_matches_full_walk_forward_without_future_data():
    series = sample_series()
    catalog = ReplayDataCatalog(series)
    days = catalog.dates_between(catalog.dates[45], catalog.dates[49])
    engine = HistoricalMarketReplay(series, MODEL_SETTINGS, ALERT_SETTINGS, days[0])
    actual = [engine.advance(catalog.read(day)) for day in days]

    full_features = build_market_features(series, 3, 20, "2024-01-01")
    model = WalkForwardRegimeModel(5, 10, 3, 2, 42)
    expected = {item["date"]: item for item in model.predict(full_features)}
    for result in actual:
        assert result.input_end == result.event_time
        assert result.state == expected[result.event_time]
        assert result.state["trained_through"] < result.event_time


def test_extending_future_records_does_not_change_replayed_day():
    series = sample_series()
    truncated = [AssetSeries(item.meta, item.frame.iloc[:46].copy()) for item in series]
    day = ReplayDataCatalog(series).dates[45]
    full_engine = HistoricalMarketReplay(series, MODEL_SETTINGS, ALERT_SETTINGS, day)
    short_engine = HistoricalMarketReplay(truncated, MODEL_SETTINGS, ALERT_SETTINGS, day)
    full = asdict(full_engine.advance(ReplayDataCatalog(series).read(day)))
    short = asdict(short_engine.advance(ReplayDataCatalog(truncated).read(day)))
    full.pop("replay_time")
    short.pop("replay_time")
    assert full == short


def test_replay_rest_websocket_pause_resume_and_reconnect():
    series = sample_series()
    catalog = ReplayDataCatalog(series)
    start = catalog.dates[45].isoformat()
    end = catalog.dates[47].isoformat()
    with TestClient(create_app(SimpleNamespace(series=series), initialize=False)) as http:
        assert http.get("/api/replay/calendar").json()["suggested_end"] == catalog.dates[-1].isoformat()
        created = http.post("/api/replay/sessions", json={"start_date": start, "end_date": end, "speed": 10})
        assert created.status_code == 201
        session_id = created.json()["id"]
        with http.websocket_connect(f"/ws/replay/{session_id}") as websocket:
            assert websocket.receive_json()["type"] == "replay_snapshot"
            assert http.post(f"/api/replay/sessions/{session_id}/start").json()["status"] == "running"
            assert websocket.receive_json()["type"] == "replay_status"
            day = websocket.receive_json()
            assert day["type"] == "replay_day"
            assert day["result"]["input_end"] == day["result"]["event_time"]
            paused = http.post(f"/api/replay/sessions/{session_id}/pause").json()
            assert paused["status"] == "paused"
            position = paused["processed_days"]
            time.sleep(0.08)
            assert http.get(f"/api/replay/sessions/{session_id}").json()["processed_days"] == position
            assert http.post(f"/api/replay/sessions/{session_id}/speed", json={"speed": 2}).json()["speed"] == 2
            assert http.post(f"/api/replay/sessions/{session_id}/resume").json()["status"] == "running"
            while True:
                message = websocket.receive_json()
                if message["type"] == "replay_day" and message["session"]["status"] == "completed":
                    break
        current = http.get("/api/replay/sessions/current").json()
        assert current["status"] == "completed"
        assert current["processed_days"] == 3
        assert current["latest_result"]["event_time"] == end
        with http.websocket_connect(f"/ws/replay/{session_id}") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["session"]["latest_result"]["event_time"] == end
        assert http.post(f"/api/replay/sessions/{session_id}/restart").json()["processed_days"] == 0
        assert http.post(f"/api/replay/sessions/{session_id}/pause").json()["status"] == "paused"
        assert http.get("/api/replay/sessions/missing").status_code == 404
        assert http.post("/api/replay/sessions", json={"start_date": end, "end_date": start}).status_code == 422


def test_single_day_completion_always_includes_the_daily_result():
    series = sample_series()
    day = ReplayDataCatalog(series).dates[45].isoformat()
    with TestClient(create_app(SimpleNamespace(series=series), initialize=False)) as http:
        session = http.post("/api/replay/sessions", json={"start_date": day, "end_date": day, "speed": 10}).json()
        session_id = session["id"]
        http.post(f"/api/replay/sessions/{session_id}/start")
        for _ in range(100):
            current = http.get(f"/api/replay/sessions/{session_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.02)
        assert current["status"] == "completed"
        assert current["latest_result"] is not None
        assert current["latest_result"]["event_time"] == day
        assert current["run_id"]
        timing = current["timing"]
        assert timing["processed_days"] == 1
        assert timing["engine_start_ms"] >= 0
        assert timing["pipeline_start_ms"] >= 0
        assert timing["last_day"]["event_date"] == day
        assert timing["last_day"]["input_ms"] >= 0
        assert timing["last_day"]["model_ms"] >= 0
        assert timing["last_day"]["ack_ms"] >= 0
        assert timing["last_day"]["total_ms"] >= timing["last_day"]["model_ms"]
