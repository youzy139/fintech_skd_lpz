from __future__ import annotations

import io
import json
from dataclasses import asdict
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.services.alert_proxy as alert_proxy_module
from app.alert_service import create_alert_app
from app.core.config import load_config
from app.core.observability import request_id_context
from app.main import create_app
from app.services.alert import AlertService
from app.services.remote_alert import AlertServiceError, RemoteAlertClient
from app.services.remote_feature import FeatureServiceError
from market_core.models.alerts import generate_alerts


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


def sample_states():
    states = [{"date": f"2024-01-{index + 1:02d}", "label": "震荡", "features": {"volatility": 0.1, "correlation": 0.2}} for index in range(31)]
    states += [{"date": f"2024-02-{index - 30:02d}", "label": "震荡", "features": {"volatility": 0.1, "correlation": 0.2}} for index in range(31, 60)]
    states.append({"date": "2024-03-01", "label": "高波动", "features": {"volatility": 0.8, "correlation": 0.9}})
    return states


def test_history_and_daily_alert_generation_have_identical_results():
    states = sample_states()
    expected = [asdict(item) for item in generate_alerts(states, 0.9, 0.9)]
    incremental = []
    for index, state in enumerate(states):
        current = generate_alerts(states[:index + 1], 0.9, 0.9)
        incremental.extend(asdict(item) for item in current if item.date == state["date"])

    assert incremental == expected
    assert {item["rule"] for item in expected} == {"HIGH_VOLATILITY", "HIGH_CORRELATION", "REGIME_CHANGE"}
    assert {item["date"] for item in expected} == {"2024-03-01"}
    assert generate_alerts([], 0.9, 0.9) == []


class FakeFeatureClient:
    def __init__(self, states):
        self.states = states
        self.paths = []
        self.closed = False

    def get(self, path):
        self.paths.append(path)
        return self.states

    def close(self):
        self.closed = True


def test_alert_service_rebuilds_history_with_shared_rules():
    feature = FakeFeatureClient(sample_states())
    service = AlertService(load_config(), feature)
    service.initialize()
    expected = [asdict(item) for item in generate_alerts(sample_states(), 0.9, 0.9)]

    assert feature.paths == ["/api/internal/alert-states"]
    assert service.list_alerts(100) == list(reversed(expected))
    assert service.list_alerts(2) == list(reversed(expected[-2:]))
    assert service.readiness() == {"status": "ok", "states": 61, "alerts": 3, "latest_state_date": "2024-03-01"}
    service.close()
    assert feature.closed


def test_alert_input_transport_preserves_missing_values():
    from app.services.market import MarketService

    states = sample_states()
    states[0]["features"]["correlation"] = float("nan")
    service = MarketService.__new__(MarketService)
    service.states = states
    transported = service.alert_states()

    assert transported[0]["features"]["correlation"] is None
    assert [asdict(item) for item in generate_alerts(transported, 0.9, 0.9)] == [asdict(item) for item in generate_alerts(states, 0.9, 0.9)]


def test_alert_application_has_independent_contract_and_identity():
    service = AlertService(load_config(), FakeFeatureClient(sample_states()))
    with TestClient(create_alert_app(service)) as http:
        response = http.get("/api/alerts?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2
        assert response.json()[0]["rule"] == "REGIME_CHANGE"
        assert http.get("/api/health").json()["service"] == "alert"
        assert http.get("/api/health/ready").json()["checks"]["alerts"]["states"] == 61
        assert http.get("/api/system/metrics").json()["scope"] == "process"
        schema = http.get("/openapi.json").json()
        assert schema["info"]["title"] == "MarketLens 预警服务"
        assert "/api/alerts" in schema["paths"]
        assert "/api/regimes" not in schema["paths"]


def test_alert_application_maps_feature_dependency_failure():
    service = SimpleNamespace(
        list_alerts=lambda limit: (_ for _ in ()).throw(FeatureServiceError("private upstream")),
        health_details=lambda: {"states": 0, "alerts": 0, "latest_state_date": None},
        readiness=lambda: {"status": "unavailable", "states": 0, "alerts": 0, "latest_state_date": None},
    )
    with TestClient(create_alert_app(service, initialize=False)) as http:
        response = http.get("/api/alerts", headers={"X-Request-ID": "trace.alert-dependency"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "feature_service_unavailable"
        assert "private upstream" not in response.text


def remote_feature_stub():
    return SimpleNamespace(
        latest_state=lambda: {"date": "2024-03-01", "label": "高波动"},
        market_readiness=lambda: {"status": "ok", "assets": 39, "states": 61},
        source_summary=lambda: {"total_records": 100},
        replay_metrics=lambda: {"replay_sessions": 0, "active_replays": 0},
        health_details=lambda: {"assets": 39, "states": 61},
        close=lambda: None,
    )


def remote_main_client(monkeypatch, opener, alert_ready):
    import app.services.feature_proxy as feature_proxy_module

    def route_upstream(request, timeout):
        if request.full_url.startswith("http://feature-service:8000"):
            return FakeResponse({"date": "2024-03-01", "label": "高波动"})
        return opener(request, timeout)

    monkeypatch.setenv("FEATURE_SERVICE_URL", "http://feature-service:8000")
    monkeypatch.setenv("ALERT_SERVICE_URL", "http://alert-service:8000")
    monkeypatch.setattr(main_module, "RemoteFeatureService", lambda config: remote_feature_stub())
    monkeypatch.setattr(main_module, "RemoteAlertClient", lambda url, timeout: SimpleNamespace(readiness=alert_ready, close=lambda: None))
    monkeypatch.setattr(alert_proxy_module, "urlopen", route_upstream)
    monkeypatch.setattr(feature_proxy_module, "urlopen", route_upstream)
    return TestClient(create_app(initialize=False))


def test_main_proxies_only_alerts_to_alert_service(monkeypatch):
    calls = []

    def open_response(request, timeout):
        calls.append((request, timeout))
        return FakeResponse([{"date": "2024-03-01", "rule": "HIGH_VOLATILITY"}])

    with remote_main_client(monkeypatch, open_response, lambda: {"status": "ok", "alerts": 1}) as http:
        response = http.get("/api/alerts?limit=1", headers={"X-Request-ID": "trace.alert-1"})
        assert response.status_code == 200
        assert response.json()[0]["rule"] == "HIGH_VOLATILITY"
        assert http.get("/api/regimes/latest").json()["label"] == "高波动"
        ready = http.get("/api/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"]["alerts"] == {"status": "ok", "alerts": 1}

    request, timeout = calls[0]
    assert request.full_url == "http://alert-service:8000/api/alerts?limit=1"
    assert request.headers["X-request-id"] == "trace.alert-1"
    assert timeout == 5.0


def test_main_preserves_alert_upstream_error(monkeypatch):
    def open_response(request, timeout):
        payload = json.dumps({"detail": "参数错误", "error": {"code": "validation_error", "request_id": "trace.alert-2"}}).encode("utf-8")
        raise HTTPError(request.full_url, 422, "Unprocessable Entity", {"Content-Type": "application/json"}, io.BytesIO(payload))

    with remote_main_client(monkeypatch, open_response, lambda: {"status": "ok"}) as http:
        response = http.get("/api/alerts?limit=0", headers={"X-Request-ID": "trace.alert-2"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_alert_outage_does_not_break_market_but_fails_readiness(monkeypatch):
    def unavailable(request, timeout):
        raise URLError("private alert address")

    def not_ready():
        raise AlertServiceError("private alert address")

    with remote_main_client(monkeypatch, unavailable, not_ready) as http:
        response = http.get("/api/alerts", headers={"X-Request-ID": "trace.alert-3"})
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        assert response.json()["error"] == {"code": "alert_service_unavailable", "message": "预警服务暂时不可用", "request_id": "trace.alert-3"}
        assert "private alert address" not in response.text
        assert http.get("/api/regimes/latest").status_code == 200
        ready = http.get("/api/health/ready")
        assert ready.status_code == 503
        assert ready.json()["checks"]["market"]["status"] == "ok"
        assert ready.json()["checks"]["catalog"]["status"] == "ok"
        assert ready.json()["checks"]["alerts"] == {"status": "unavailable"}


@pytest.mark.parametrize("status,name,value", [(429, "Retry-After", "17"), (503, "Retry-After", "Wed, 21 Oct 2026 07:28:00 GMT"), (401, "WWW-Authenticate", 'Bearer realm="marketlens"'), (405, "Allow", "GET")])
def test_alert_proxy_preserves_upstream_control_headers(monkeypatch, status, name, value):
    payload = b'{"detail":"upstream rejection"}'

    def rejected(request, timeout):
        headers = {"Content-Type": "application/problem+json", name: value, "Connection": "close", "X-Private-Upstream": "internal"}
        raise HTTPError(request.full_url, status, "Rejected", headers, io.BytesIO(payload))

    with remote_main_client(monkeypatch, rejected, lambda: {"status": "ok"}) as http:
        response = http.get("/api/alerts", headers={"X-Request-ID": "trace.header-alert"})
        assert response.status_code == status
        assert response.content == payload
        assert response.headers[name] == value
        assert response.headers["content-type"] == "application/problem+json"
        assert response.headers["x-request-id"] == "trace.header-alert"
        assert "connection" not in response.headers
        assert "x-private-upstream" not in response.headers


def test_remote_alert_client_contract_and_validation():
    calls = []

    def open_response(request, timeout):
        calls.append((request, timeout))
        return FakeResponse({"status": "ok", "checks": {"alerts": {"status": "ok", "alerts": 3}}})

    client = RemoteAlertClient("http://alert-service:8000/", 3, open_response)
    token = request_id_context.set("trace.alert-client")
    try:
        assert client.readiness()["alerts"] == 3
    finally:
        request_id_context.reset(token)
    request, timeout = calls[0]
    assert request.full_url == "http://alert-service:8000/api/health/ready"
    assert request.headers["X-request-id"] == "trace.alert-client"
    assert timeout == 3.0
    with pytest.raises(ValueError, match="HTTP"):
        RemoteAlertClient("file:///tmp/alert")
    with pytest.raises(ValueError, match="超时"):
        RemoteAlertClient("http://alert-service:8000", 0)
    invalid = RemoteAlertClient("http://alert-service:8000", opener=lambda request, timeout: FakeResponse(b"not-json"))
    with pytest.raises(AlertServiceError, match="暂时不可用"):
        invalid.get("/api/alerts")
