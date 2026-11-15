from __future__ import annotations

import json

import pandas as pd
import pytest

from app.services.stability import load_stability_report, write_json
from market_core.models.evaluation import compare_states, evaluate_stability, summarize_states


def state(day, regime_id, label, trained_through):
    return {
        "date": day, "regime_id": regime_id, "cluster": regime_id,
        "label": f"{label} · C{regime_id}", "trained_through": trained_through,
    }


def test_ari_is_invariant_to_regime_id_permutation_and_semantics_are_separate():
    left = [state("2024-01-01", 0, "震荡平衡", "2023-12-29"), state("2024-01-02", 1, "趋势上涨", "2023-12-29"), state("2024-01-03", 0, "震荡平衡", "2024-01-01")]
    right = [state("2024-01-01", 5, "震荡平衡", "2023-12-29"), state("2024-01-02", 9, "趋势上涨", "2023-12-29"), state("2024-01-03", 5, "下跌承压", "2024-01-01")]
    result = compare_states(left, right)
    assert result["adjusted_rand_index"] == 1
    assert result["semantic_agreement"] == pytest.approx(2 / 3)
    changed = [right[0], state("2024-01-02", 5, "趋势上涨", "2023-12-29"), right[2]]
    assert compare_states(left, changed)["adjusted_rand_index"] < 1
    assert compare_states(left, right[1:])["common_state_days"] == 2


def test_switch_duration_and_refit_boundary_denominators():
    states = [
        state("2024-01-01", 0, "震荡平衡", "2023-12-29"),
        state("2024-01-02", 0, "震荡平衡", "2024-01-01"),
        state("2024-01-03", 1, "趋势上涨", "2024-01-01"),
        state("2024-01-04", 1, "趋势上涨", "2024-01-03"),
        state("2024-01-05", 2, "下跌承压", "2024-01-03"),
    ]
    result = summarize_states(states)
    assert result["switch_count"] == 2
    assert result["refit_boundary_count"] == 2
    assert result["refit_boundary_switch_count"] == 0
    assert result["refit_boundary_switch_share"] == 0
    assert result["refit_boundary_switch_rate"] == 0
    assert result["episode_count"] == 3
    assert result["median_duration_days"] == 2
    assert result["p90_duration_days"] == 2
    assert result["max_duration_days"] == 2
    unchanged = summarize_states(states[:2])
    assert unchanged["refit_boundary_switch_share"] is None
    assert unchanged["refit_boundary_switch_rate"] == 0
    json.dumps(unchanged, allow_nan=False)


def evaluation_frame():
    index = pd.bdate_range("2020-01-01", periods=18)
    values = {
        "market_return": [0.001 * ((day % 5) - 2) for day in range(18)],
        "volatility": [0.1 + 0.02 * (day % 4) for day in range(18)],
        "momentum": [0.01 * ((day % 7) - 3) for day in range(18)],
        "correlation": [0.2 + 0.05 * (day % 3) for day in range(18)],
        "trend": [0.01 * (day % 2) for day in range(18)],
        "sample_count": [4] * 18,
    }
    return pd.DataFrame(values, index=index)


def test_complete_grid_is_reproducible_and_covers_every_period():
    settings = {
        "minimum_history": 4, "training_window": 4, "refit_interval": 2,
        "cluster_count": 2, "random_seed": 42, "regime_identity": "centroid-alignment-v1",
    }
    report, daily = evaluate_stability(evaluation_frame(), settings, (4, 6), (2, 3), (42, 7))
    repeated, _ = evaluate_stability(evaluation_frame(), settings, (4, 6), (2, 3), (42, 7))
    assert report == repeated
    assert report["grid"]["run_count"] == 8
    assert len(report["runs"]) == 8
    assert report["reference_run_id"] == "w4-r2-s42"
    assert sum(run["is_reference"] for run in report["runs"]) == 1
    assert len(daily) == 8
    assert all(len(states) == 14 for states in daily.values())
    assert len(report["comparisons"]) == 4 * 28
    assert report["summary"]["all"]["pair_count"] == 28
    assert report["summary"]["all"]["common_state_days"] == {"min": 14, "median": 14, "max": 14}
    assert report["summary"]["holdout"]["pair_count"] == 28
    assert report["summary"]["holdout"]["adjusted_rand_index"] == {"min": None, "median": None, "max": None}
    assert report["coverage_sensitivity"]["method"] == "output_filter_only_no_refit"
    assert report["coverage_sensitivity"]["periods"]["all"][0]["eligible_days"] == 14
    assert report["coverage_sensitivity"]["periods"]["all"][-1]["eligible_days"] == 0
    json.dumps(report, allow_nan=False)


def test_grid_validation_requires_baseline_and_aligned_identity():
    settings = {"minimum_history": 4, "training_window": 4, "refit_interval": 2, "cluster_count": 2, "random_seed": 42}
    with pytest.raises(ValueError, match="基准参数"):
        evaluate_stability(evaluation_frame(), settings, (6,), (2,), (42,))
    with pytest.raises(ValueError, match="不能为空"):
        evaluate_stability(evaluation_frame(), settings, (), (2,), (42,))
    with pytest.raises(ValueError, match="centroid-alignment-v1"):
        evaluate_stability(evaluation_frame(), {**settings, "regime_identity": "local-cluster-v1"}, (4,), (2,), (42,))


def test_report_loading_rejects_missing_stale_and_malformed_files(tmp_path):
    database = tmp_path / "market.db"
    metadata = {
        "input_version": "input-v1",
        "feature_contract": {"feature_version": "features-v1"},
        "model_parameters": {"training_window": 756},
    }
    with pytest.raises(FileNotFoundError, match="尚未生成"):
        load_stability_report(database, metadata)
    report = {
        "report_type": "regime_stability", "evaluation_version": "stability-v1",
        "input_version": "input-v1", "feature_version": "features-v1",
        "model_parameters": {"training_window": 756},
    }
    path = tmp_path / "benchmarks" / "regime-stability.json"
    write_json(path, report)
    assert load_stability_report(database, metadata) == report
    write_json(path, {**report, "input_version": "old-input"})
    with pytest.raises(ValueError, match="不匹配"):
        load_stability_report(database, metadata)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="不可读取"):
        load_stability_report(database, metadata)
