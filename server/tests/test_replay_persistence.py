from __future__ import annotations

import json
import time
from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import load_config
from app.main import create_app
from app.services.replay import ReplayDataCatalog
from app.services.replay_store import ReplayStore
from market_core.models.replay import HistoricalMarketReplay
from server.tests.test_replay import sample_series


def configure(monkeypatch, database_path):
    config = replace(load_config(), database_path=database_path, replay={"interval_ms": 100})
    monkeypatch.setattr(main_module, "load_config", lambda: config)


def app(series, database_path):
    return TestClient(create_app(SimpleNamespace(series=series), initialize=False, replay_store=ReplayStore(database_path)))


def wait_for(http, session_id, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = http.get(f"/api/replay/sessions/{session_id}").json()
        if current["status"] == "failed":
            raise AssertionError(current["error"])
        if predicate(current):
            return current
        time.sleep(0.02)
    raise TimeoutError(session_id)


def test_completed_session_and_result_backfill_survive_restart(monkeypatch, tmp_path):
    series = sample_series()
    catalog = ReplayDataCatalog(series)
    days = catalog.dates[45:48]
    database = tmp_path / "replay.db"
    configure(monkeypatch, database)
    with app(series, database) as http:
        created = http.post("/api/replay/sessions", json={"start_date": days[0].isoformat(), "end_date": days[-1].isoformat(), "speed": 1}).json()
        session_id = created["id"]
        http.post(f"/api/replay/sessions/{session_id}/start")
        completed = wait_for(http, session_id, lambda item: item["status"] == "completed")
        first = http.get(f"/api/replay/sessions/{session_id}/results?after=0&limit=2").json()
        assert [item["sequence"] for item in first["results"]] == [1, 2]
        assert first["has_more"] is True
        remaining = http.get(f"/api/replay/sessions/{session_id}/results?after=2").json()
        assert [item["sequence"] for item in remaining["results"]] == [3]
        assert remaining["has_more"] is False

    with app(series, database) as http:
        restored = http.get("/api/replay/sessions/current").json()
        assert restored["status"] == "completed"
        assert restored["processed_days"] == 3
        assert restored["latest_sequence"] == 3
        assert restored["latest_result"] == completed["latest_result"]
        restored_results = http.get(f"/api/replay/sessions/{session_id}/results?after=1").json()
        assert [item["sequence"] for item in restored_results["results"]] == [2, 3]


def test_unfinished_session_recovers_from_saved_results(monkeypatch, tmp_path):
    series = sample_series()
    catalog = ReplayDataCatalog(series)
    days = catalog.dates[45:48]
    database = tmp_path / "replay.db"
    configure(monkeypatch, database)
    with app(series, database) as http:
        created = http.post("/api/replay/sessions", json={"start_date": days[0].isoformat(), "end_date": days[-1].isoformat(), "speed": 1}).json()
        session_id = created["id"]
        http.post(f"/api/replay/sessions/{session_id}/start")
        wait_for(http, session_id, lambda item: item["latest_sequence"] >= 1)
        paused = http.post(f"/api/replay/sessions/{session_id}/pause").json()
        assert 0 < paused["processed_days"] < 3
        run_id = paused["run_id"]
        saved_results = paused["processed_days"]

    with app(series, database) as http:
        recovered = http.get("/api/replay/sessions/current").json()
        assert recovered["status"] == "paused"
        assert recovered["recovery"]["state"] == "paused"
        assert recovered["processed_days"] == saved_results
        assert recovered["run_id"] == run_id
        resumed = http.post(f"/api/replay/sessions/{session_id}/resume", headers={"Idempotency-Key": "resume-1"}).json()
        assert resumed["recovery"]["state"] == "rebuilding"
        duplicate = http.post(f"/api/replay/sessions/{session_id}/resume", headers={"Idempotency-Key": "resume-1"}).json()
        assert duplicate["run_id"] == resumed["run_id"]
        completed = wait_for(http, session_id, lambda item: item["status"] == "completed")
        assert completed["run_id"] == run_id
        assert completed["recovery"]["state"] == "completed"
        assert completed["recovery"]["count"] == 1
        assert completed["recovery"]["rebuild_ms"] >= 0
        results = http.get(f"/api/replay/sessions/{session_id}/results?after=0").json()["results"]
        assert [item["sequence"] for item in results] == [1, 2, 3]
        assert [item["result"]["event_time"] for item in results] == [day.isoformat() for day in days]

    config = load_config()
    engine = HistoricalMarketReplay(series, config.model, config.alerts, days[0])
    expected = None
    for day in days:
        expected = engine.advance(catalog.read(day))
    assert completed["latest_result"]["state"] == expected.state
    assert completed["latest_result"]["features"] == expected.features


def test_create_idempotency_key_reuses_session_and_rejects_mismatch(monkeypatch, tmp_path):
    series = sample_series()
    catalog = ReplayDataCatalog(series)
    day = catalog.dates[45]
    database = tmp_path / "replay.db"
    configure(monkeypatch, database)
    payload = {"start_date": day.isoformat(), "end_date": day.isoformat(), "speed": 1}
    with app(series, database) as http:
        first = http.post("/api/replay/sessions", json=payload, headers={"Idempotency-Key": "create-1"})
        second = http.post("/api/replay/sessions", json=payload, headers={"Idempotency-Key": "create-1"})
        assert first.json()["id"] == second.json()["id"]
        mismatch = http.post("/api/replay/sessions", json={**payload, "speed": 2}, headers={"Idempotency-Key": "create-1"})
        assert mismatch.status_code == 422
        assert "幂等键" in mismatch.json()["detail"]


def test_legacy_non_finite_payloads_are_null_when_read(tmp_path):
    store = ReplayStore(tmp_path / "legacy-replay.db")
    result = {"event_time": "2024-01-01", "features": {"momentum": float("nan"), "correlation": float("inf")}}
    snapshot = {
        "id": "legacy", "mode": "local", "status": "paused", "start_date": "2024-01-01",
        "end_date": "2024-01-02", "speed": 1, "processed_days": 1, "latest_result": result,
    }
    store.save_session(snapshot)
    store.record_result(snapshot, 1, result)
    store.save_operation("legacy", "pause", "pause-1", {}, snapshot)
    with store.lock, store.connection:
        store.connection.execute("UPDATE replay_sessions SET snapshot_json = ? WHERE id = 'legacy'", (json.dumps(snapshot),))
        store.connection.execute("UPDATE replay_results SET result_json = ? WHERE session_id = 'legacy'", (json.dumps(result),))
        store.connection.execute("UPDATE replay_operations SET snapshot_json = ? WHERE session_id = 'legacy'", (json.dumps(snapshot),))

    assert store.load_sessions()[0]["latest_result"]["features"] == {"momentum": None, "correlation": None}
    assert store.load_session("legacy")["latest_result"]["features"]["momentum"] is None
    assert store.latest_result("legacy")[1]["features"]["correlation"] is None
    assert store.results("legacy")["results"][0]["result"]["features"]["momentum"] is None
    assert store.operation("legacy", "pause", "pause-1", {})["latest_result"]["features"]["correlation"] is None
    store.close()
