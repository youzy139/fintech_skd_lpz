from __future__ import annotations

import numpy as np
import pandas as pd

from market_core.models.alerts import generate_alerts
from market_core.models.features import build_market_features
from market_core.models.regime import WalkForwardRegimeModel
from market_core.domain.market import AssetMeta, AssetSeries
from datetime import date
from pathlib import Path


def asset(name: str, values: list[float], dates: pd.DatetimeIndex, field: str = "close") -> AssetSeries:
    meta = AssetMeta("测试", name, name, field, "测试", date(2020, 1, 1), date(2026, 1, 1), len(values), Path(name))
    return AssetSeries(meta, pd.DataFrame({"date": dates, "value": values}))


def test_yield_series_is_excluded_from_price_returns():
    dates = pd.date_range("2024-01-01", periods=80)
    prices = [asset("price_a", np.linspace(100, 120, 80), dates), asset("price_b", np.linspace(80, 90, 80), dates), asset("yield", np.linspace(2, 3, 80), dates, "yield")]
    features = build_market_features(prices, 10, 20, "2024-01-01")
    assert len(features) > 0
    assert features["sample_count"].max() == 2


def model() -> WalkForwardRegimeModel:
    return WalkForwardRegimeModel(80, 120, 20, 3, 42)


def feature_frame(length: int) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    frame = pd.DataFrame({"market_return": rng.normal(0, 0.01, length), "volatility": rng.uniform(0.1, 0.4, length), "momentum": rng.normal(0, 0.1, length), "correlation": rng.uniform(0.1, 0.7, length), "trend": 0.0, "sample_count": 5}, index=pd.date_range("2020-01-01", periods=length))
    return frame


def test_walk_forward_history_does_not_change_when_future_is_appended():
    features = feature_frame(150)
    original = model().predict(features.iloc[:130])
    extended = model().predict(features)
    assert original == extended[:len(original)]
    assert all(item["trained_through"] < item["date"] for item in extended)


def test_alert_rule_contains_evidence():
    dates = pd.date_range("2024-01-01", periods=71).strftime("%Y-%m-%d")
    states = [{"date": dates[index], "label": "震荡", "features": {"volatility": 0.1, "correlation": 0.2}} for index in range(70)]
    states.append({"date": dates[70], "label": "高波动", "features": {"volatility": 0.8, "correlation": 0.2}})
    alerts = generate_alerts(states, 0.9, 0.9)
    assert any(item.rule == "HIGH_VOLATILITY" for item in alerts)
    assert any(item.rule == "REGIME_CHANGE" for item in alerts)
