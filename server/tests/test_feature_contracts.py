from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app
from app.services.market import MarketService
from app.services.replay import ReplayDataCatalog, ReplayManager
from market_core.domain.market import DataQuality
from market_core.models.feature_contracts import feature_contract, market_input_version
from market_core.models.replay import HistoricalMarketReplay
from server.tests.test_replay import ALERT_SETTINGS, MODEL_SETTINGS, sample_series


def test_feature_version_tracks_calculation_not_training_parameters():
    original = feature_contract(MODEL_SETTINGS)
    assert feature_contract({**MODEL_SETTINGS, "random_seed": 10, "training_window": 30}) == original
    assert feature_contract(dict(reversed(list(MODEL_SETTINGS.items())))) == original
    changed = feature_contract({**MODEL_SETTINGS, "volatility_window": 7})
    assert changed["feature_version"] != original["feature_version"]
    volatility = next(item for item in changed["features"] if item["name"] == "volatility")
    assert volatility["window"] == volatility["minimum_observations"] == 7
    assert "7 行" in volatility["formula"]
    assert sum(item["model_input"] for item in original["features"]) == 4
    assert next(item for item in original["features"] if item["name"] == "correlation")["minimum_observations"] == 20


def test_input_digest_ignores_future_but_detects_historical_and_field_changes():
    series = sample_series()
    through = series[0].frame.iloc[46]["date"].date()
    expected = market_input_version(series, through)
    series[0].frame.loc[60, "value"] += 100
    assert market_input_version(series, through) == expected
    series[0].frame.loc[20, "value"] += 1
    assert market_input_version(series, through) != expected
    before_field = market_input_version(series, through)
    series[0] = replace(series[0], meta=replace(series[0].meta, field="yield"))
    assert market_input_version(series, through) != before_field


def test_metadata_is_served_from_initialized_model_not_live_configuration(tmp_path):
    series = sample_series()
    config = replace(load_config(), database_path=tmp_path / "market.db", model=dict(MODEL_SETTINGS))
    service = MarketService(config)
    service.repository.load_all = lambda: (series, DataQuality(catalog_records=2, available_assets=2, loaded_assets=2, total_rows=160))
    try:
        service.initialize()
        expected = feature_contract(MODEL_SETTINGS)
        config.model["volatility_window"] = 15
        with TestClient(create_app(service, initialize=False)) as http:
            response = http.get("/api/features/metadata")
            assert response.status_code == 200
            assert response.json()["feature_contract"] == expected
            assert response.json()["input_version"] == market_input_version(series)
            assert response.json()["state_model_version"] == service.latest_state()["model_version"]
    finally:
        service.close()


def test_new_session_resumes_with_frozen_parameters_after_restart(tmp_path):
    series = sample_series()
    catalog = ReplayDataCatalog(series)
    days = catalog.dates[45:48]
    config = replace(load_config(), database_path=tmp_path / "pinned.db", model=dict(MODEL_SETTINGS), alerts=dict(ALERT_SETTINGS), replay={"interval_ms": 0})

    async def scenario():
        owner = ReplayManager(SimpleNamespace(series=series), config)
        created = owner.create(days[0], days[-1], 10)
        session = owner.get(created["id"])
        expected_engine = HistoricalMarketReplay(series, MODEL_SETTINGS, ALERT_SETTINGS, days[0])
        first = asdict(expected_engine.advance(catalog.read(days[0])))
        snapshot = session.snapshot()
        snapshot.update(status="paused", processed_days=1, latest_sequence=1, latest_result=first, run_id="pinned-run")
        owner.store.record_result(snapshot, 1, first)
        before = owner.store.results(session.id)["results"][0]
        await owner.close()
        changed = replace(config, model={**MODEL_SETTINGS, "random_seed": 1, "training_window": 7, "refit_interval": 1, "volatility_window": 4}, alerts={"volatility_quantile": 0.55, "correlation_quantile": 0.55})
        restored = ReplayManager(SimpleNamespace(series=series), changed)
        try:
            session = restored.get(created["id"])
            assert session.snapshot()["calculation_contract"] == created["calculation_contract"]
            await session.resume()
            await asyncio.wait_for(session.task, 15)
            assert session.clock.status == "completed", session.clock.error
            results = restored.store.results(session.id)["results"]
            assert results[0] == before
            for row, day in zip(results[1:], days[1:]):
                expected = asdict(expected_engine.advance(catalog.read(day)))
                assert row["result"]["state"] == expected["state"]
                assert row["result"]["features"] == expected["features"]
                assert row["result"]["alerts"] == list(expected["alerts"])
            fresh = restored.create(days[0], days[-1], 10)
            assert fresh["calculation_contract"]["version"] != created["calculation_contract"]["version"]
        finally:
            await restored.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["history", "future", "contract"])
def test_resume_checks_input_and_contract_without_rewriting_results(tmp_path, change):
    series = sample_series()
    catalog = ReplayDataCatalog(series)
    config = replace(load_config(), database_path=tmp_path / "input.db", model=MODEL_SETTINGS, alerts=ALERT_SETTINGS)
    owner = ReplayManager(SimpleNamespace(series=series), config)
    created = owner.create(catalog.dates[45], catalog.dates[47], 10)
    session = owner.get(created["id"])
    first = asdict(session._build_engine().advance(catalog.read(catalog.dates[45])))
    snapshot = session.snapshot()
    snapshot.update(status="paused", processed_days=1, latest_sequence=1, latest_result=first)
    owner.store.record_result(snapshot, 1, first)
    before = owner.store.results(session.id)["results"]
    asyncio.run(owner.close())
    if change in {"history", "future"}:
        series[0].frame.loc[20 if change == "history" else 60, "value"] += 10
    restored = ReplayManager(SimpleNamespace(series=series), config)
    try:
        session = restored.get(created["id"])
        if change == "contract":
            session.calculation_contract["model"]["random_seed"] = 123
        if change == "future":
            assert session._build_engine().model_settings["training_window"] == MODEL_SETTINGS["training_window"]
        else:
            with pytest.raises(ValueError, match="契约校验失败|输入已改变"):
                session._build_engine()
        assert restored.store.results(session.id)["results"] == before
    finally:
        asyncio.run(restored.close())
