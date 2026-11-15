from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_core.models.alerts import generate_alerts
from market_core.models.features import average_correlation, build_market_features, build_price_panels
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


def test_price_panel_alignment_matches_concat_for_irregular_unsorted_inputs():
    dates_a = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-04"])
    dates_b = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = [asset("A", [103.0, 101.0, 104.0], dates_a), asset("B", [82.0, 83.0], dates_b)]
    expected = pd.concat([item.frame.rename(columns={"value": item.meta.code}).set_index("date") for item in prices], axis=1).sort_index()
    actual, _ = build_price_panels(prices)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_price_panel_rejects_duplicate_dates():
    dates = pd.to_datetime(["2024-01-01", "2024-01-01"])
    with pytest.raises(ValueError, match="重复日期"):
        build_price_panels([asset("A", [100.0, 101.0], dates)])


def test_positional_correlation_window_matches_prefix_tail_reference():
    dates = pd.bdate_range("2024-01-01", periods=100)
    rng = np.random.default_rng(2026)
    returns = pd.DataFrame(rng.normal(0, 0.01, (100, 4)), index=dates, columns=list("ABCD"))
    returns.iloc[::9, 1] = np.nan
    returns.iloc[3:17, 2] = np.nan
    start = dates[23]

    expected_values = {}
    for day in dates[dates >= start]:
        sample = returns.loc[:day, list("ABCD")].tail(20)
        corr = sample.corr(min_periods=20).to_numpy()
        upper = corr[np.triu_indices_from(corr, k=1)]
        valid = upper[np.isfinite(upper)]
        expected_values[day] = float(valid.mean()) if valid.size else np.nan
    expected = pd.Series(expected_values, name="correlation")

    actual = average_correlation(returns, 20, start)
    pd.testing.assert_series_equal(actual, expected, check_exact=True)


def test_single_output_day_matches_full_feature_history_exactly():
    dates = pd.bdate_range("2024-01-01", periods=100)
    rng = np.random.default_rng(42)
    prices = [asset(name, 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 100))), dates) for name in ("A", "B", "C")]
    full = build_market_features(prices, 10, 20, "2024-01-01")
    event_day = full.index[-1]
    daily = build_market_features(prices, 10, 20, "2024-01-01", event_day.strftime("%Y-%m-%d"))
    pd.testing.assert_frame_equal(daily, full.loc[[event_day]], check_exact=True, check_freq=False)


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
