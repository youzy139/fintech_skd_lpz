from __future__ import annotations

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from server.benchmarks.independent_user_performance import compare_api_baseline, execute_mixed, execute_persistent


def test_mixed_load_uses_independent_sessions_and_rotates_scenarios():
    calls = []

    def synthetic_call(base_url, path, token, timeout):
        calls.append((token, path))
        return (5.0 if path == "/read" else 10.0, 200)

    result = execute_mixed("http://127.0.0.1:18000", ["/read", "/query"], ["user-a", "user-b", "user-c"], 2, 1, synthetic_call)

    assert result["requests"] == 6
    assert result["successful"] == 6
    assert result["users"] == 3
    assert Counter(token for token, _ in calls) == {"user-a": 2, "user-b": 2, "user-c": 2}
    assert Counter(calls) == {
        ("user-a", "/read"): 1, ("user-a", "/query"): 1,
        ("user-b", "/read"): 1, ("user-b", "/query"): 1,
        ("user-c", "/read"): 1, ("user-c", "/query"): 1,
    }
    assert result["scenarios"]["/read"]["requests"] == 3
    assert result["scenarios"]["/query"]["requests"] == 3


def test_mixed_load_rejects_empty_identities():
    with pytest.raises(ValueError):
        execute_mixed("http://127.0.0.1:18000", ["/read"], [], 1, 1)


def test_persistent_load_reuses_one_connection_per_user():
    connections = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            connections.append((self.headers["Authorization"], self.client_address[1]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = execute_persistent(f"http://127.0.0.1:{server.server_port}", ["/read", "/query"], ["user-a", "user-b"], 3, 2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["requests"] == 6
    assert result["successful"] == 6
    by_user = {}
    for token, port in connections:
        by_user.setdefault(token, set()).add(port)
    assert set(by_user) == {"Bearer user-a", "Bearer user-b"}
    assert all(len(ports) == 1 for ports in by_user.values())
    assert result["scenarios"]["/read"]["requests"] == 3
    assert result["scenarios"]["/query"]["requests"] == 3


def comparable_report(new_connection_p95=433.145, keep_alive_p95=398.439):
    group = lambda p95: {"requests": 505, "latency_ms": {"p95": p95}}
    return {
        "generated_at": "2026-11-15T00:00:00+00:00",
        "configuration": {"users": 101, "rounds": 5, "timeout_seconds": 10, "scenarios": {"latest": "/latest"}, "rate_limit_mode": "local", "server_thread_pool_size": 40},
        "environment": {"platform": "test", "python": "3.12", "cpu_count": 24, "git_revision": "baseline"},
        "measurement": {"new_connection_per_request": group(new_connection_p95), "keep_alive_per_user": group(keep_alive_p95)},
        "target_evaluation": {"all_requests_successful": True},
    }


def test_baseline_comparison_reports_decrease_and_increase_with_samples():
    baseline = comparable_report()
    current = comparable_report(347.789, 407.769)
    current["generated_at"] = "2026-11-16T00:00:00+00:00"
    current["environment"]["git_revision"] = "current"
    comparison = compare_api_baseline(current, baseline)
    assert comparison["comparison_version"] == "api-performance-baseline-comparison-v1"
    assert comparison["groups"]["new_connection_per_request"]["delta_ms"] == -85.356
    assert comparison["groups"]["new_connection_per_request"]["sample_count"] == 505
    assert comparison["groups"]["keep_alive_per_user"]["delta_ms"] == 9.33
    assert comparison["groups"]["keep_alive_per_user"]["change_percent"] > 0


def test_baseline_comparison_rejects_different_load_or_incomplete_reports():
    baseline = comparable_report()
    current = comparable_report()
    current["configuration"]["rounds"] = 4
    try:
        compare_api_baseline(current, baseline)
        raise AssertionError("不同轮次不应比较")
    except ValueError as error:
        assert "配置不一致" in str(error)
    current = comparable_report()
    current["target_evaluation"]["all_requests_successful"] = False
    try:
        compare_api_baseline(current, baseline)
        raise AssertionError("失败报告不应比较")
    except ValueError as error:
        assert "全部请求成功" in str(error)
