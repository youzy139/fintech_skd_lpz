from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

import app.main as main_module
import app.services.feature_proxy as proxy_module
from app.core.observability import request_id_context
from app.feature_service import create_feature_app
from app.main import create_app
from app.services.feature_proxy import forward_feature_websocket, websocket_url
from app.services.remote_feature import FeatureServiceError, RemoteFeatureClient


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode("utf-8")


def remote_service_stub():
    state = {"date": "2024-01-02", "label": "趋势上涨", "model_version": "test"}
    return SimpleNamespace(
        feature=SimpleNamespace(get=lambda path: {"openapi": "3.1.0", "info": {"title": "MarketLens", "version": "0.3.3"}, "paths": {"/api/regimes": {}, "/api/replay/sessions": {}, "/api/data/summary": {}}}),
        assets=lambda: [{"code": "TEST"}],
        latest_state=lambda: state,
        health_details=lambda: {"storage_mode": "distributed", "assets": 1, "states": 1},
        market_readiness=lambda: {"status": "ok", "assets": 1, "states": 1},
        replay_metrics=lambda: {"replay_sessions": 2, "active_replays": 1},
        source_summary=lambda: {"total_files": 1, "imported_files": 1, "total_records": 2, "errors": 0, "groups": []},
        data_version=lambda: "version-1",
        close=lambda: None,
    )


def remote_client(monkeypatch, opener):
    monkeypatch.setenv("FEATURE_SERVICE_URL", "http://feature-service:8000")
    monkeypatch.setattr(main_module, "RemoteFeatureService", lambda config: remote_service_stub())
    monkeypatch.setattr(proxy_module, "urlopen", opener)
    return TestClient(create_app(initialize=False))


def test_remote_mode_proxies_market_and_replay_contracts(monkeypatch):
    calls = []

    def open_response(request, timeout):
        calls.append((request, timeout))
        if request.full_url.startswith("http://feature-service:8000/api/replay/sessions"):
            return FakeResponse({"id": "session-1", "status": "pending"}, 201)
        return FakeResponse([{"date": "2024-01-02", "label": "趋势上涨"}])

    with remote_client(monkeypatch, open_response) as http:
        response = http.get("/api/regimes?start=2024-01-01&limit=1", headers={"X-Request-ID": "trace.feature-1"})
        assert response.status_code == 200
        assert response.json()[0]["label"] == "趋势上涨"
        created = http.post("/api/replay/sessions", json={"start_date": "2024-01-01", "end_date": "2024-01-02"}, headers={"Idempotency-Key": "create-1"})
        assert created.status_code == 201
        assert created.json()["id"] == "session-1"
        assert http.app.state.replays is None

    get_request, timeout = calls[0]
    assert urlsplit(get_request.full_url).query == "start=2024-01-01&limit=1"
    assert get_request.headers["X-request-id"] == "trace.feature-1"
    assert timeout == 10.0
    post_request, _ = calls[1]
    assert post_request.headers["Idempotency-key"] == "create-1"
    assert json.loads(post_request.data)["end_date"] == "2024-01-02"


def test_remote_mode_preserves_upstream_errors_and_graphql(monkeypatch):
    def open_response(request, timeout):
        payload = json.dumps({"detail": "会话不存在", "error": {"code": "not_found", "request_id": "trace.feature-2"}}).encode("utf-8")
        raise HTTPError(request.full_url, 404, "Not Found", {"Content-Type": "application/json"}, io.BytesIO(payload))

    with remote_client(monkeypatch, open_response) as http:
        missing = http.get("/api/replay/sessions/missing", headers={"X-Request-ID": "trace.feature-2"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        response = http.post("/graphql", json={"query": "{ assets latestState sourceSummary }"})
        assert response.json()["data"] == {
            "assets": [{"code": "TEST"}],
            "latestState": {"date": "2024-01-02", "label": "趋势上涨", "model_version": "test"},
            "sourceSummary": {"total_files": 1, "imported_files": 1, "total_records": 2, "errors": 0, "groups": []},
        }
        assert http.get("/api/health").json()["assets"] == 1
        assert http.get("/api/system/metrics").json()["replay_sessions"] == 2
        schema = http.get("/openapi.json").json()
        assert {"/api/regimes", "/api/replay/sessions", "/api/data/summary"} <= set(schema["paths"])


def test_remote_mode_maps_transport_failure_to_stable_503(monkeypatch):
    def unavailable(request, timeout):
        raise URLError("private upstream address")

    with remote_client(monkeypatch, unavailable) as http:
        response = http.get("/api/regimes/latest", headers={"X-Request-ID": "trace.feature-3"})
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        assert response.json()["error"] == {"code": "feature_service_unavailable", "message": "特征与状态服务暂时不可用", "request_id": "trace.feature-3"}
        assert "private upstream address" not in response.text


def test_remote_feature_client_and_websocket_url():
    calls = []

    def open_response(request, timeout):
        calls.append((request, timeout))
        return FakeResponse({"date": "2024-01-02", "label": "趋势上涨"})

    client = RemoteFeatureClient("http://feature-service:8000/", 3, open_response)
    token = request_id_context.set("trace.feature-client")
    try:
        assert client.get("/api/regimes/latest")["label"] == "趋势上涨"
    finally:
        request_id_context.reset(token)
    request, timeout = calls[0]
    assert request.full_url == "http://feature-service:8000/api/regimes/latest"
    assert request.headers["X-request-id"] == "trace.feature-client"
    assert timeout == 3.0
    assert websocket_url("http://feature-service:8000", "/ws/replay/session-1", "after=2") == "ws://feature-service:8000/ws/replay/session-1?after=2"
    assert websocket_url("https://example.com", "/ws/replay", "") == "wss://example.com/ws/replay"
    with pytest.raises(ValueError, match="HTTP"):
        RemoteFeatureClient("file:///tmp/feature")
    with pytest.raises(ValueError, match="超时"):
        RemoteFeatureClient("http://feature-service:8000", 0)


def test_remote_feature_client_hides_invalid_response():
    client = RemoteFeatureClient("http://feature-service:8000", opener=lambda request, timeout: FakeResponse(b"not-json"))
    with pytest.raises(FeatureServiceError, match="暂时不可用"):
        client.get("/api/health")


def test_feature_service_has_independent_application_identity():
    app = create_feature_app(initialize=False)
    assert app.title == "MarketLens 特征与状态服务"


def test_websocket_proxy_preserves_upstream_close_code(monkeypatch):
    class Upstream:
        close_code = 4404
        close_reason = ""

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ConnectionClosedError(Close(4404, ""), None)

        async def close(self):
            return None

    class Connection:
        async def __aenter__(self):
            return Upstream()

        async def __aexit__(self, *args):
            return None

    class Client:
        url = SimpleNamespace(path="/ws/replay/not-found", query="")

        def __init__(self):
            self.close_codes = []

        async def accept(self):
            return None

        async def receive(self):
            await asyncio.Event().wait()

        async def close(self, code=1000, reason=""):
            self.close_codes.append(code)

    upstream = Upstream()
    monkeypatch.setattr(proxy_module.websockets, "connect", lambda *args, **kwargs: Connection())
    client = Client()
    asyncio.run(forward_feature_websocket(client, "http://feature-service:8000", 1))
    assert client.close_codes[0] == 4404
