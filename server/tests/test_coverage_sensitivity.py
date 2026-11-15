from __future__ import annotations

import json

import pytest

from market_core.models.coverage import evaluate_coverage_sensitivity


def state(day, count):
    return {"date": day, "features": {"sample_count": count}}


def alert(day, rule):
    return {"date": day, "rule": rule}


def periods():
    return {
        "all": {"start": None, "end": None},
        "validation": {"start": "2022-01-01", "end": "2022-12-31"},
    }


def test_thresholds_filter_existing_days_and_alerts_without_recomputing_them():
    states = [state("2022-01-01", 1), state("2022-01-02", 4), state("2022-01-03", 8), state("2023-01-01", 31), state("2023-01-02", None)]
    alerts = [
        alert("2022-01-01", "HIGH_VOLATILITY"), alert("2022-01-02", "HIGH_VOLATILITY"),
        alert("2022-01-03", "HIGH_CORRELATION"), alert("2022-01-03", "REGIME_CHANGE"),
        alert("2023-01-01", "REGIME_CHANGE"), alert("2023-01-02", "HIGH_VOLATILITY"),
    ]
    report = evaluate_coverage_sensitivity(states, alerts, periods(), (1, 5, 31))
    assert report["method"] == "output_filter_only_no_refit"
    threshold_five = report["periods"]["all"][1]
    assert threshold_five["minimum_sample_count"] == 5
    assert threshold_five["state_days"] == 5
    assert threshold_five["eligible_days"] == 2
    assert threshold_five["excluded_days"] == 3
    assert threshold_five["eligible_share"] == .4
    assert threshold_five["alerts"]["HIGH_VOLATILITY"] == {"original": 3, "retained": 0, "excluded": 3}
    assert threshold_five["alerts"]["HIGH_CORRELATION"] == {"original": 1, "retained": 1, "excluded": 0}
    assert threshold_five["alerts"]["REGIME_CHANGE"] == {"original": 2, "retained": 2, "excluded": 0}
    validation = report["periods"]["validation"][1]
    assert validation["state_days"] == 3
    assert validation["eligible_days"] == 1
    assert validation["alerts"]["REGIME_CHANGE"]["original"] == 1
    assert validation["alerts"]["REGIME_CHANGE"]["retained"] == 1
    assert report["periods"]["all"][2]["eligible_days"] == 1
    json.dumps(report, allow_nan=False)


def test_empty_periods_keep_missing_share_and_validate_thresholds():
    report = evaluate_coverage_sensitivity([], [], periods())
    assert report["periods"]["all"][0]["state_days"] == 0
    assert report["periods"]["all"][0]["eligible_share"] is None
    with pytest.raises(ValueError, match="正整数"):
        evaluate_coverage_sensitivity([], [], periods(), (0,))
    with pytest.raises(ValueError, match="正整数"):
        evaluate_coverage_sensitivity([], [], periods(), ())
