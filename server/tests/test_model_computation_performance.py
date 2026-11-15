from __future__ import annotations

import json
from copy import deepcopy

import pandas as pd
import pytest

from app.services.model_performance import load_performance_report
from app.services.stability import write_json
from market_core.models.feature_contracts import feature_contract, market_input_version, model_parameters
from market_core.models.features import build_market_features
from server.benchmarks.model_computation_performance import (
    PERFORMANCE_VERSION,
    build_performance_report,
    compare_performance_baseline,
    measure_replay_run,
    summarize_latency,
)
from server.tests.test_replay import ALERT_SETTINGS, MODEL_SETTINGS, ReplayDataCatalog, sample_series


def test_single_day_probe_separates_actual_refit_and_preserves_results():
    series = sample_series()
    days = ReplayDataCatalog(series).dates[45:50]
    ticks = iter([0.0, 0.1, 0.2, 0.21, 0.22, 0.25])
    run = measure_replay_run(series, MODEL_SETTINGS, ALERT_SETTINGS, days[:1], 1, clock=lambda: next(ticks))

    day = run["days"][0]
    assert run["initialization_ms_excluded_from_daily_samples"] == 100
    assert day["feature_ms"] == 10
    assert day["regime_ms"] == 30
    assert day["feature_calls"] == 1
    assert day["regime_calls"] == 1
    assert day["valid_feature"] and day["state_generated"]
    with pytest.raises(StopIteration):
        next(ticks)

    report = build_performance_report(series, MODEL_SETTINGS, ALERT_SETTINGS, days, runs=2)
    assert report["performance_version"] == PERFORMANCE_VERSION
    assert report["complete"] and report["result_consistent"] and report["targets_conclusive"]
    assert all("daily_results" not in run for run in report["runs"])
    feature_days = build_market_features(series, 3, 20, "2024-01-01")
    indices = [feature_days.index.get_loc(pd.Timestamp(day)) for day in days]
    expected_refit = [(index - MODEL_SETTINGS["minimum_history"]) % MODEL_SETTINGS["refit_interval"] == 0 for index in indices]
    assert [day["refit"] for day in report["runs"][0]["days"]] == expected_refit
    assert report["summary"]["features"]["sample_count"] == 10
    assert report["summary"]["regime_non_refit"]["sample_count"] == 2 * expected_refit.count(False)
    assert report["summary"]["regime_refit"]["sample_count"] == 2 * expected_refit.count(True)
    assert report["summary"]["regime_all"]["sample_count"] == 10
    assert all(day["trained_through"] < day["event_date"] for run in report["runs"] for day in run["days"])
    json.dumps(report, allow_nan=False)


def test_days_without_valid_features_or_states_are_not_zero_latency_successes():
    series = sample_series()
    days = ReplayDataCatalog(series).dates[:3]
    run = measure_replay_run(series, MODEL_SETTINGS, ALERT_SETTINGS, days, 1)

    assert all(day["feature_ms"] is None and day["regime_ms"] is None for day in run["days"])
    assert all(day["feature_calls"] == 1 and day["regime_calls"] == 0 for day in run["days"])
    assert run["summary"]["features"]["sample_count"] == 0
    assert run["summary"]["features"]["latency_ms"]["p95"] is None
    assert run["summary"]["features"]["p95_within_target"] is None


def test_latency_summary_keeps_empty_groups_and_threshold_boundary_explicit():
    empty = summarize_latency([], 50)
    assert empty["sample_count"] == 0
    assert empty["p95_within_target"] is None
    assert summarize_latency([10, 20, 50], 50)["p95_within_target"] is False
    assert summarize_latency([10, 20, 30], 50)["p95_within_target"] is True


def test_baseline_comparison_reports_signed_changes_and_rejects_mismatched_scope():
    series = sample_series()
    days = ReplayDataCatalog(series).dates[45:47]
    current = build_performance_report(series, MODEL_SETTINGS, ALERT_SETTINGS, days, runs=1, data_profile="synthetic-test")
    baseline = deepcopy(current)
    baseline["summary"]["features"]["latency_ms"]["p95"] = current["summary"]["features"]["latency_ms"]["p95"] * 2

    comparison = compare_performance_baseline(current, baseline)
    feature_change = comparison["stages"]["features"]
    assert feature_change["delta_ms"] < 0
    assert feature_change["change_percent"] == -50
    assert feature_change["sample_count"] == 2
    assert comparison["comparison_version"] == "performance-baseline-comparison-v1"
    json.dumps(comparison, allow_nan=False)

    wrong_interval = deepcopy(baseline)
    wrong_interval["configuration"]["event_start"] = "2020-01-01"
    with pytest.raises(ValueError, match="口径不一致"):
        compare_performance_baseline(current, wrong_interval)
    wrong_samples = deepcopy(baseline)
    wrong_samples["summary"]["features"]["sample_count"] += 1
    with pytest.raises(ValueError, match="样本数不一致"):
        compare_performance_baseline(current, wrong_samples)
    wrong_environment = deepcopy(baseline)
    wrong_environment["environment"]["cpu_count"] += 1
    with pytest.raises(ValueError, match="运行环境不一致"):
        compare_performance_baseline(current, wrong_environment)
    incomplete = {**baseline, "complete": False}
    with pytest.raises(ValueError, match="完整"):
        compare_performance_baseline(current, incomplete)


def test_report_loader_rejects_missing_stale_and_unreadable_reports(tmp_path):
    series = sample_series()
    days = ReplayDataCatalog(series).dates[45:47]
    report = build_performance_report(series, MODEL_SETTINGS, ALERT_SETTINGS, days, runs=1)
    database = tmp_path / "market.db"
    path = tmp_path / "benchmarks" / "model-computation-performance.json"
    metadata = {
        "input_version": market_input_version(series),
        "feature_contract": feature_contract(MODEL_SETTINGS),
        "model_parameters": model_parameters(MODEL_SETTINGS),
    }
    with pytest.raises(FileNotFoundError):
        load_performance_report(database, metadata)

    write_json(path, report)
    feature_days = build_market_features(series, 3, 20, "2024-01-01")
    indices = [feature_days.index.get_loc(pd.Timestamp(day)) for day in days]
    expected_refit_count = sum((index - MODEL_SETTINGS["minimum_history"]) % MODEL_SETTINGS["refit_interval"] == 0 for index in indices)
    assert load_performance_report(database, metadata)["summary"]["regime_refit"]["sample_count"] == expected_refit_count
    stale = {**report, "input_version": "stale-input"}
    write_json(path, stale)
    with pytest.raises(ValueError, match="不匹配"):
        load_performance_report(database, metadata)

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="不可读取"):
        load_performance_report(database, metadata)
