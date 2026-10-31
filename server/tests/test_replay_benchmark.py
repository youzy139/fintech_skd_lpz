from __future__ import annotations

from app.core.observability import percentile
from app.services.replay_benchmark import comparable_result, result_digest, results_close, summarize_runs


def test_percentile_uses_deterministic_nearest_rank():
    assert percentile([], 0.5) is None
    assert percentile([4, 1, 3, 2], 0.5) == 2
    assert percentile([4, 1, 3, 2], 0.95) == 4


def test_result_digest_ignores_only_wall_clock_processing_time():
    result = {"event_time": "2026-04-27", "state": {"label": "下跌承压"}, "replay_time": "2026-04-27T10:00:00Z"}
    assert comparable_result(result) == {"event_time": "2026-04-27", "state": {"label": "下跌承压"}}
    assert result_digest(result) == result_digest({**result, "replay_time": "2026-04-27T11:00:00Z"})
    assert result_digest(result) != result_digest({**result, "event_time": "2026-04-28"})


def test_result_comparison_tolerates_transport_rounding_but_not_financial_changes():
    left = {"state": {"label": "下跌承压", "confidence": 0.46326576179344287}}
    right = {"state": {"label": "下跌承压", "confidence": 0.463265761793443}}
    assert results_close(left, right)
    assert not results_close(left, {"state": {"label": "趋势上涨", "confidence": right["state"]["confidence"]}})
    assert not results_close(left, {"state": {"label": "下跌承压", "confidence": 0.5}})


def test_run_summary_reports_actual_samples():
    runs = [
        {"total_ms": 100.0, "first_result_ms": 40.0, "records_per_second": 10.0, "temperature": "cold"},
        {"total_ms": 200.0, "first_result_ms": 60.0, "records_per_second": 20.0, "temperature": "warm"},
    ]
    summary = summarize_runs(runs)
    assert summary["total_ms"]["p50"] == 100.0
    assert summary["total_ms"]["p95"] == 200.0
    assert summary["first_result_ms"]["p50"] == 40.0
    assert summary["records_per_second"]["p95"] == 20.0
    assert summary["cold"]["total_ms"]["p50"] == 100.0
    assert summary["warm"]["total_ms"]["p50"] == 200.0
