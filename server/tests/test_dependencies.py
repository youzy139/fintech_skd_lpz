from __future__ import annotations

import asyncio
from dataclasses import replace
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app
from app.services.dependencies import DependencyMonitor
from server.tests.test_api import fake_service


def test_disabled_dependencies_do_not_run_network_probes():
    config = load_config()
    assert all(not getattr(config, name).get("enabled", False) for name in ("mysql", "clickhouse", "redis", "minio", "kafka", "flink"))
    report = asyncio.run(DependencyMonitor(config).snapshot())
    assert report["status"] == "ok"
    assert len(report["checks"]) == 6
    assert {item["status"] for item in report["checks"]} == {"disabled"}
    assert all(item["latency_ms"] is None for item in report["checks"])


def test_enabled_probe_reports_success_and_failure_with_latency(monkeypatch):
    config = replace(load_config(), redis={**load_config().redis, "enabled": True})
    monitor = DependencyMonitor(config)
    monkeypatch.setattr(monitor, "_redis", lambda: {"probe": "PING"})
    report = asyncio.run(monitor.snapshot())
    redis_check = next(item for item in report["checks"] if item["name"] == "redis")
    assert redis_check["status"] == "ok"
    assert redis_check["latency_ms"] >= 0

    def fail():
        raise ConnectionError("private host details")
    monkeypatch.setattr(monitor, "_redis", fail)
    report = asyncio.run(monitor.snapshot())
    redis_check = next(item for item in report["checks"] if item["name"] == "redis")
    assert report["status"] == "degraded"
    assert redis_check["status"] == "unavailable"
    assert redis_check["error_type"] == "ConnectionError"
    assert "private" not in str(report)


def test_dependency_api_includes_circuit_and_cache_state():
    service = fake_service()
    with TestClient(create_app(service, initialize=False)) as http:
        response = http.get("/api/system/dependencies")
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "ok"
    assert report["governance"]["mode"] == "local"
    assert report["governance"]["circuit"]["state"] == "closed"


def test_kafka_probe_uses_supported_metadata_client(monkeypatch):
    created = []

    class Consumer:
        def __init__(self, **settings):
            created.append(settings)

        async def start(self):
            pass

        async def topics(self):
            return {"topic"}

        async def stop(self):
            pass

    monkeypatch.setattr("app.services.dependencies.AIOKafkaConsumer", Consumer)
    result = asyncio.run(DependencyMonitor(load_config())._kafka())
    assert result == {"probe": "Kafka metadata"}
    assert created[0]["request_timeout_ms"] == 1000
    assert "api_version_auto_timeout_ms" not in created[0]
