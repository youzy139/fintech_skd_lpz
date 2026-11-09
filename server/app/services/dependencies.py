from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Awaitable, Callable
from urllib.request import urlopen

import clickhouse_connect
import pymysql
import redis
from aiokafka import AIOKafkaConsumer
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import AppConfig


Probe = Callable[[], Awaitable[dict[str, Any]]]


class DependencyMonitor:
    def __init__(self, config: AppConfig, timeout_seconds: float = 2.0):
        self.config = config
        self.timeout_seconds = timeout_seconds

    async def _sync(self, method: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        return await asyncio.to_thread(method)

    def _mysql(self) -> dict[str, Any]:
        settings = self.config.mysql
        connection = pymysql.connect(
            host=settings["host"], port=int(settings["port"]), user=settings["user"], password=settings["password"],
            database=settings["database"], connect_timeout=1, read_timeout=1, write_timeout=1,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone()[0] == 1
            return {"probe": "SELECT 1"}
        finally:
            connection.close()

    def _clickhouse(self) -> dict[str, Any]:
        settings = self.config.clickhouse
        client = clickhouse_connect.get_client(
            host=settings["host"], port=int(settings["port"]), username=settings["username"], password=settings["password"],
            database=settings["database"], secure=bool(settings.get("secure", False)), connect_timeout=1, send_receive_timeout=1,
        )
        try:
            result = client.query("SELECT 1").result_rows
            assert result[0][0] == 1
            return {"probe": "SELECT 1"}
        finally:
            client.close()

    def _redis(self) -> dict[str, Any]:
        settings = self.config.redis
        client = redis.Redis(
            host=settings["host"], port=int(settings["port"]), db=int(settings["db"]), password=settings["password"] or None,
            socket_connect_timeout=0.3, socket_timeout=0.3, retry=Retry(NoBackoff(), 0),
        )
        try:
            assert client.ping()
            return {"probe": "PING"}
        finally:
            client.close()

    def _minio(self) -> dict[str, Any]:
        settings = self.config.minio
        scheme = "https" if settings.get("secure", False) else "http"
        with urlopen(f"{scheme}://{settings['endpoint']}/minio/health/live", timeout=1) as response:
            assert response.status == 200
        return {"probe": "GET /minio/health/live"}

    def _flink(self) -> dict[str, Any]:
        with urlopen(self.config.flink["rest_url"].rstrip("/") + "/jobs/overview", timeout=1) as response:
            assert response.status == 200
        return {"probe": "GET /jobs/overview"}

    async def _kafka(self) -> dict[str, Any]:
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self.config.kafka["bootstrap_servers"], request_timeout_ms=1000,
        )
        try:
            await consumer.start()
            await consumer.topics()
            return {"probe": "Kafka metadata"}
        finally:
            await consumer.stop()

    async def _run(self, name: str, enabled: bool, probe: Probe) -> dict[str, Any]:
        if not enabled:
            return {"name": name, "status": "disabled", "latency_ms": None}
        started = monotonic()
        try:
            details = await asyncio.wait_for(probe(), self.timeout_seconds)
            return {"name": name, "status": "ok", "latency_ms": round((monotonic() - started) * 1000, 3), **details}
        except Exception as error:
            return {"name": name, "status": "unavailable", "latency_ms": round((monotonic() - started) * 1000, 3), "error_type": type(error).__name__}

    async def snapshot(self) -> dict[str, Any]:
        probes = {
            "mysql": (self.config.mysql["enabled"], lambda: self._sync(self._mysql)),
            "clickhouse": (self.config.clickhouse["enabled"], lambda: self._sync(self._clickhouse)),
            "redis": (self.config.redis["enabled"], lambda: self._sync(self._redis)),
            "minio": (self.config.minio["enabled"], lambda: self._sync(self._minio)),
            "kafka": (self.config.kafka["enabled"], self._kafka),
            "flink": (self.config.flink["enabled"], lambda: self._sync(self._flink)),
        }
        checks = await asyncio.gather(*(self._run(name, enabled, probe) for name, (enabled, probe) in probes.items()))
        return {
            "status": "degraded" if any(item["status"] == "unavailable" for item in checks) else "ok",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        }
