from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pandas as pd

from market_core.domain.market import AssetMeta, AssetSeries
from market_core.models.model_card import build_model_card


def asset(code, field, values, declared_rows=None):
    meta = AssetMeta("测试", code, code, field, "测试", date(2020, 1, 1), date(2020, 1, 6), declared_rows or len(values), Path("test.csv"))
    dates = pd.date_range("2020-01-01", periods=len(values))
    return AssetSeries(meta, pd.DataFrame({"date": dates, "value": values}), duplicate_dates=1, invalid_rows=2)


def test_model_card_reports_input_exclusions_and_post_warmup_gaps():
    close = asset("CLOSE", "close", [100, 101, 102, 103, 0, 105])
    yield_series = asset("YIELD", "yield", [1.2, 1.3], declared_rows=3)
    features = pd.DataFrame(
        {"sample_count": [1, 1, 1]},
        index=pd.to_datetime(["2020-01-03", "2020-01-04", "2020-01-06"]),
    )
    states = [{"date": "2020-01-04"}, {"date": "2020-01-06"}]
    card = build_model_card([close, yield_series], features, states, "2020-01-02", ["缺失资产"])
    close_row = next(item for item in card["assets"] if item["code"] == "CLOSE")
    yield_row = next(item for item in card["assets"] if item["code"] == "YIELD")
    assert close_row["model_input"] is True
    assert close_row["analysis_rows"] == 5
    assert close_row["nonpositive_rows"] == 1
    assert close_row["observed_vs_declared"] == 1
    assert yield_row["model_input"] is False
    assert "百分数" in yield_row["exclusion_reason"]
    assert yield_row["observed_vs_declared"] == 2 / 3
    assert card["loaded_series"] == 2
    assert card["price_assets"] == 1
    assert card["excluded_series"] == 1
    assert card["catalog_missing_assets"] == ["缺失资产"]
    assert card["valid_observations"] == 8
    assert card["price_observations"] == 6
    assert card["nonpositive_price_rows"] == 1
    assert card["invalid_rows"] == 4
    assert card["duplicate_dates"] == 2
    assert card["union_price_observation_days"] == 5
    assert card["post_first_feature_union_days"] == 4
    assert card["covered_after_first_feature_days"] == 3
    assert card["dropped_after_first_feature_days"] == 1
    assert card["dropped_after_first_feature_dates"] == ["2020-01-05"]
    assert card["post_first_feature_coverage"] == .75
    assert card["state_days"] == 2
    assert card["state_sample_count"]["median"] == 1
    assert card["state_days_below_price_assets"] == 0
    json.dumps(card, allow_nan=False)


def test_model_card_preserves_missing_coverage_instead_of_zero_filling():
    series = asset("CLOSE", "close", [100, 101])
    features = pd.DataFrame({"sample_count": pd.Series(dtype=float)}, index=pd.DatetimeIndex([]))
    card = build_model_card([series], features, [], "2020-01-01")
    assert card["feature_days"] == 0
    assert card["first_feature_day"] is None
    assert card["post_first_feature_coverage"] is None
    assert card["feature_sample_count"] == {"min": None, "median": None, "max": None, "latest": None}
    assert card["state_days"] == 0
    json.dumps(card, allow_nan=False)
