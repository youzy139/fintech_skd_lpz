from __future__ import annotations

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from server.benchmarks.independent_user_performance import execute_mixed, execute_persistent


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
