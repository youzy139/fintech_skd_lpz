from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.core.resilience import CircuitBreaker
from app.main import create_app
from app.services.cache import RedisJsonCache
from app.services.feature_cache import FeatureSnapshotCache
from app.services.market import MarketService
from app.services.remote_feature import RemoteFeatureService
from market_core.domain.market import DataQuality
from server.tests.test_cache import FakeRedis
from server.tests.test_feature_service import FakeResponse
from server.tests.test_replay import MODEL_SETTINGS, sample_series


def snapshot(client, metadata=None, state=None, breaker=None):
    metadata = metadata or {"feature_contract": {"feature_version": "features-1"}, "data_version": "data-1", "input_version": "input-1", "model_parameters": {"random_seed": 42}}
    state = state or {"date": "2024-01-02", "features": {"volatility": 0.2, "momentum": None}, "contributions": [], "model_version": "model-1", "regime_identity": "centroid-alignment-v1"}
    return FeatureSnapshotCache(metadata, state, RedisJsonCache(client, "test:features", 60, breaker))


def test_shared_hits_return_isolated_authoritative_values_and_never_replay():
    client = FakeRedis()
    first, second = snapshot(client), snapshot(client)
    expected = first.read()
    result = second.read()
    assert result == expected
    result["features"]["volatility"] = 999
    assert second.read() == expected
    assert second.status()["validated_hits"] == 2
    assert second.status()["view"] == "current-market"
    assert all("replay" not in key for key in client.values)


def test_nonfinite_features_are_null_on_cache_miss_and_hit():
    client = FakeRedis()
    state = {"date": "2024-01-02", "features": {"volatility": float("inf"), "momentum": float("nan")}, "contributions": [{"value": -float("inf")}], "model_version": "model-1"}
    cached = snapshot(client, state=state)
    for _ in range(2):
        result = cached.read()
        assert result["features"] == {"volatility": None, "momentum": None}
        assert result["contributions"] == [{"value": None}]


@pytest.mark.parametrize("field", ["feature_version", "data_version", "input_version", "model_parameters", "date", "model_version", "regime_identity", "value"])
def test_each_calculation_identity_change_isolated_from_old_key(field):
    client = FakeRedis()
    old = snapshot(client)
    old.read()
    metadata = deepcopy(old._identity)
    metadata["feature_contract"] = {"feature_version": metadata["feature_version"]}
    state = {**old._value, "regime_identity": "centroid-alignment-v1"}
    if field == "feature_version":
        metadata["feature_contract"][field] = "features-2"
    elif field in {"data_version", "input_version", "model_parameters"}:
        metadata[field] = {"random_seed": 1} if field == "model_parameters" else "changed"
    elif field == "value":
        state["features"]["volatility"] = 0.3
    else:
        state[field] = "2024-01-03" if field == "date" else "changed"
    new = snapshot(client, metadata, state)
    assert new.key != old.key
    assert new.read() == {name: state[name] for name in ("date", "features", "contributions", "model_version")}
    assert new.status()["validated_hits"] == 0
    assert len(client.values) == 2


@pytest.mark.parametrize("corruption", ["json", "identity", "value", "missing", "nan"])
def test_corrupt_cache_is_rejected_and_repaired(corruption):
    import json

    client = FakeRedis()
    cached = snapshot(client)
    expected = cached.read()
    envelope = json.loads(client.values[cached.key])
    if corruption == "json":
        client.values[cached.key] = "not-json"
    else:
        if corruption == "identity":
            envelope["identity"]["scope"] = "other-scope"
        elif corruption == "value":
            envelope["value"]["features"]["volatility"] = 999
        elif corruption == "missing":
            del envelope["value"]
        else:
            envelope["value"]["features"]["volatility"] = float("nan")
        client.values[cached.key] = json.dumps(envelope)
    assert cached.read() == expected
    assert cached.read() == expected
    assert cached.status()["validated_hits"] == 1


def test_outage_opens_circuit_then_recovers_without_changing_features():
    now = [0.0]
    client = FakeRedis()
    cached = snapshot(client, breaker=CircuitBreaker(2, 5, clock=lambda: now[0]))
    expected = cached.read()
    client.available = False
    assert cached.read() == expected
    calls = client.calls
    assert cached.read() == expected
    assert client.calls == calls
    assert cached.status()["shared"]["circuit"]["state"] == "open"
    client.available = True
    now[0] = 6
    assert cached.read() == expected
    assert cached.status()["shared"]["circuit"]["state"] == "closed"


def test_initialized_service_api_uses_cache_and_keeps_nonfinite_values_null(tmp_path):
    config = replace(load_config(), database_path=tmp_path / "market.db", model=dict(MODEL_SETTINGS))
    service = MarketService(config)
    service.repository.load_all = lambda: (sample_series(), DataQuality(catalog_records=2, available_assets=2, loaded_assets=2, total_rows=160))
    client = FakeRedis()
    service._feature_cache = RedisJsonCache(client, "test:features", 60)
    try:
        service.initialize()
        expected = service.latest_features()
        service.config.model["random_seed"] = 999
        with TestClient(create_app(service, initialize=False)) as http:
            assert http.get("/api/features/latest").json() == expected
            assert http.get("/api/system/feature-cache").json()["validated_hits"] >= 1
            client.available = False
            assert http.get("/api/features/latest").json() == expected
        assert service.feature_metadata()["model_parameters"]["random_seed"] != 999
    finally:
        service.close()
    assert client.closed


def test_admin_cache_status_comes_from_feature_service_with_bounded_timeout(tmp_path):
    calls = []
    config = replace(load_config(), database_path=tmp_path / "remote.db", feature_service={"url": "http://feature:8000", "timeout_seconds": 2})

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse({"enabled": True, "validated_hits": 11})

    service = RemoteFeatureService(config, opener)
    try:
        assert service.feature_cache_status()["validated_hits"] == 11
        assert calls == [("http://feature:8000/api/system/feature-cache", 2)]
    finally:
        service.close()
