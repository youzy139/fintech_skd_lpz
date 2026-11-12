from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]


def main():
    parser = argparse.ArgumentParser(description="独立合成数据的真实 Redis 特征路径验证，不是正式性能基准")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=16379)
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/feature-cache-validation.json")
    args = parser.parse_args()
    from server.benchmarks.e2e_server import prepare

    with tempfile.TemporaryDirectory(prefix="marketlens-feature-cache-") as directory:
        prepare(Path(directory))
        os.environ["REDIS_ENABLED"] = "false"
        from app.core.auth import auth_store, store_for
        from app.core.config import load_config
        from app.core.resilience import CircuitBreaker
        from app.main import create_app
        from app.services.cache import RedisJsonCache
        from app.services.market import MarketService
        from fastapi.testclient import TestClient

        config = load_config()
        settings = {**config.redis, "enabled": True, "host": args.host, "port": args.port, "password": os.getenv("FEATURE_CACHE_TEST_PASSWORD", ""), "namespace": "marketlens:feature-validation:" + uuid.uuid4().hex, "ttl_seconds": 1}
        service = MarketService(replace(config, redis=settings))
        raw = service._feature_cache.client
        raw.ping()
        try:
            service.initialize()
            expected = service.latest_features()
            snapshot = service._feature_snapshot
            assert raw.ttl(snapshot.key) in (0, 1)
            assert service.latest_features() == expected
            first_hits = service.feature_cache_status()["validated_hits"]
            time.sleep(1.1)
            assert raw.get(snapshot.key) is None
            assert service.latest_features() == expected
            raw.set(snapshot.key, '{"identity":{},"value":{"features":{"momentum":999}}}', ex=1)
            assert service.latest_features() == expected
            assert service.feature_cache_status()["rejected"] == 1
            with socket.socket() as unused:
                unused.bind(("127.0.0.1", 0))
                unavailable_port = unused.getsockname()[1]
                failed = RedisJsonCache.from_config({**settings, "host": "127.0.0.1", "port": unavailable_port})
                service._feature_cache.client = failed.client
                service._feature_cache.breaker = CircuitBreaker(2, 1)
                for _ in range(3):
                    assert service.latest_features() == expected
                assert service.feature_cache_status()["shared"]["circuit"]["state"] == "open"
                service._feature_cache.client = raw
                time.sleep(1.1)
                assert service.latest_features() == expected
                assert service.feature_cache_status()["shared"]["circuit"]["state"] == "closed"
                failed.close()
            auth_store()
            code = (Path(directory) / "auth-bootstrap.txt").read_text()
            with TestClient(create_app(service, initialize=False)) as http:
                response = http.post("/api/auth/bootstrap", json={"username": "feature-test-admin", "password": "synthetic-only-password-123", "setup_code": code}, headers={"Origin": "http://localhost:5174"})
                assert response.status_code == 200
                for _ in range(20):
                    assert http.get("/api/features/latest").json() == expected
                report = http.get("/api/system/feature-cache").json()
            result = {"schema": "feature-cache-validation-v1", "data": "3 synthetic assets, 1000 business days", "redis_version": raw.info("server")["redis_version"], "checks": {"real_redis_hit": first_hits > 0, "ttl_expiry": True, "corrupt_envelope_repaired": True, "refused_endpoint_fallback": True, "circuit_recovery": True, "authenticated_api_reads": 20}, "cache": report, "limitations": ["in-process FastAPI TestClient; no network API latency measurement", "single synthetic snapshot; not representative concurrent-user performance", "outage injected by refused loopback endpoint; Redis process not stopped", "no real account, source data, or application volume used"]}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=True))
        finally:
            service.close()
            store_for.cache_clear()


if __name__ == "__main__":
    main()
