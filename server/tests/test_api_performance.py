from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "api_performance.py"
SPEC = importlib.util.spec_from_file_location("api_performance", SCRIPT)
assert SPEC and SPEC.loader
api_performance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api_performance)


def test_latency_summary_keeps_statuses_and_percentiles():
    result = api_performance.summarize([10, 20, 30, 40], [200, 200, 429, 200], elapsed=2)
    assert result["requests"] == 4
    assert result["successful"] == 3
    assert result["statuses"] == {"200": 3, "429": 1}
    assert result["latency_ms"]["p50"] == 20
    assert result["latency_ms"]["p95"] == 40
    assert result["throughput_requests_per_second"] == 2


def test_concurrent_executor_reports_real_wall_time_and_does_not_hide_429(monkeypatch):
    calls = []

    def fake_call(base, path, token, timeout):
        calls.append((base, path, token, timeout))
        return 75, 429 if len(calls) == 1 else 200

    monkeypatch.setattr(api_performance, "call", fake_call)
    result = api_performance.execute("http://test", "/api/test", 10, 3, ["a", "b"], 2)
    assert result["requests"] == 10
    assert result["successful"] == 9
    assert result["statuses"]["429"] == 1
    assert result["p95_within_50ms"] is False
    assert result["workers"] == 3
    assert len(calls) == 10
