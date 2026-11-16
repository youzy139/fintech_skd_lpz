"""Measure the production latest-feature cache path against a real local Redis."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.core.observability import percentile
from app.services.feature_cache_performance import benchmark_source_sha256, source_sha256
from app.services.replay_benchmark import git_revision
from server.benchmarks.e2e_server import prepare
from server.benchmarks.independent_user_performance import read_json, wait_ready


def summarize_latencies(values: Sequence[float], target_ms: float | None = 10) -> dict[str, Any]:
    samples = [float(value) for value in values]
    p95 = percentile(samples, 0.95)
    return {
        "sample_count": len(samples),
        "latency_ms": {
            "p50": percentile(samples, 0.5),
            "p95": p95,
            "p99": percentile(samples, 0.99),
            "min": round(min(samples), 3) if samples else None,
            "max": round(max(samples), 3) if samples else None,
            "mean": round(sum(samples) / len(samples), 3) if samples else None,
        },
        "target_p95_ms": target_ms,
        "p95_within_target": p95 < target_ms if p95 is not None and target_ms is not None else None,
    }


def measure_reads(
    reader: Callable[[], dict[str, Any]],
    expected: dict[str, Any],
    rounds: int,
    samples_per_round: int,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    if rounds < 1 or samples_per_round < 1:
        raise ValueError("热特征测量轮次和每轮样本数必须大于 0")
    all_durations: list[float] = []
    round_metrics = []
    for round_index in range(rounds):
        durations = []
        for _ in range(samples_per_round):
            started = clock()
            value = reader()
            durations.append((clock() - started) * 1000)
            if value != expected:
                raise AssertionError("Redis 热特征返回值与权威快照不一致")
        all_durations.extend(durations)
        round_metrics.append({"round_index": round_index + 1, **summarize_latencies(durations)})
    return {**summarize_latencies(all_durations), "rounds": round_metrics, "result_consistent": True}


def measure_http_keep_alive(host: str, port: int, token: str, expected: dict[str, Any], samples: int, timeout: float) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("HTTP 热特征测量样本数必须大于 0")
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    durations = []
    statuses: dict[str, int] = {}
    try:
        for _ in range(samples):
            started = time.perf_counter()
            connection.request("GET", "/api/features/latest", headers={"Accept": "application/json", "Authorization": "Bearer " + token})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            durations.append((time.perf_counter() - started) * 1000)
            statuses[str(response.status)] = statuses.get(str(response.status), 0) + 1
            if response.status != 200 or payload != expected:
                raise AssertionError("HTTP 热特征状态或返回值与权威快照不一致")
    finally:
        connection.close()
    return {**summarize_latencies(durations, None), "statuses": statuses, "result_consistent": True}


def request_status(host: str, port: int, path: str, token: str, timeout: float) -> int:
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", path, headers={"Accept": "application/json", "Authorization": "Bearer " + token})
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="真实本机 Redis 的生产热特征路径基准；使用独立合成数据、身份库和命名空间")
    parser.add_argument("--host", default="127.0.0.1", help="隔离基准 HTTP 监听地址，只能为本机")
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=16379)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--samples", type=int, default=200, help="每轮生产服务有效命中样本数")
    parser.add_argument("--http-samples", type=int, default=200)
    parser.add_argument("--miss-samples", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--ready-timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/feature-cache-performance.json")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("隔离热特征基准只能监听本机")
    if not 1 <= args.port <= 65535 or not 1 <= args.redis_port <= 65535:
        parser.error("HTTP 或 Redis 端口无效")
    if min(args.rounds, args.samples, args.http_samples, args.miss_samples) < 1 or min(args.timeout, args.ready_timeout) <= 0:
        parser.error("轮次、样本数和超时参数必须大于 0")
    with socket.socket() as reservation:
        if reservation.connect_ex((args.host, args.port)) == 0:
            parser.error(f"固定基准端口 {args.port} 已被占用；请先停止所属预览，不自动更换端口")

    with tempfile.TemporaryDirectory(prefix="marketlens-feature-performance-") as directory:
        root = Path(directory)
        prepare(root)
        namespace = "marketlens:feature-performance:" + uuid.uuid4().hex
        config_path = root / "config.json"
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        raw_config["redis"].update({"enabled": True, "host": args.redis_host, "port": args.redis_port, "ttl_seconds": 300, "namespace": namespace})
        config_path.write_text(json.dumps(raw_config), encoding="utf-8")
        os.environ["REDIS_PASSWORD"] = os.getenv("FEATURE_CACHE_TEST_PASSWORD", "")
        os.environ.pop("SERVER_THREAD_POOL_SIZE", None)

        from app.core.auth import auth_store, store_for
        from app.core.config import load_config
        from app.core.resilience import CircuitBreaker
        from app.services.cache import RedisJsonCache
        from app.services.market import MarketService

        config = load_config()
        service = MarketService(config)
        second_service: MarketService | None = None
        process: subprocess.Popen | None = None
        try:
            raw = service._feature_cache.client
            server_info = raw.info("server")
            service.initialize()
            expected = service.latest_features()
            snapshot = service._feature_snapshot
            if raw.get(snapshot.key) is None:
                raise AssertionError("首次读取未写入真实 Redis")

            miss_durations = []
            for _ in range(args.miss_samples):
                raw.delete(snapshot.key)
                started = time.perf_counter()
                value = service.latest_features()
                miss_durations.append((time.perf_counter() - started) * 1000)
                if value != expected:
                    raise AssertionError("缓存未命中回填结果与权威快照不一致")

            direct = measure_reads(service.latest_features, expected, args.rounds, args.samples)
            second_service = MarketService(config)
            second_service.initialize()
            second_expected = second_service.latest_features()
            cross_instance_hit = second_expected == expected and second_service.feature_cache_status()["validated_hits"] >= 1
            if not cross_instance_hit:
                raise AssertionError("第二个独立服务对象未命中同一版本化 Redis 快照")

            raw.pexpire(snapshot.key, 1)
            time.sleep(0.05)
            ttl_expiry = raw.get(snapshot.key) is None and service.latest_features() == expected
            raw.set(snapshot.key, '{"identity":{},"value":{"features":{"momentum":999}}}', ex=300)
            corrupt_rejected = service.latest_features() == expected and service.feature_cache_status()["rejected"] >= 1

            with socket.socket() as unused:
                unused.bind(("127.0.0.1", 0))
                unavailable_port = unused.getsockname()[1]
                failed = RedisJsonCache.from_config({**config.redis, "host": "127.0.0.1", "port": unavailable_port})
                original_client = service._feature_cache.client
                original_breaker = service._feature_cache.breaker
                try:
                    service._feature_cache.client = failed.client
                    service._feature_cache.breaker = CircuitBreaker(2, 0.05)
                    outage_fallback = all(service.latest_features() == expected for _ in range(3))
                    circuit_opened = service.feature_cache_status()["shared"]["circuit"]["state"] == "open"
                    service._feature_cache.client = raw
                    time.sleep(0.06)
                    circuit_recovery = service.latest_features() == expected and service.feature_cache_status()["shared"]["circuit"]["state"] == "closed"
                finally:
                    service._feature_cache.client = original_client
                    service._feature_cache.breaker = original_breaker
                    failed.close()

            store = auth_store()
            password = "synthetic-feature-benchmark-123"
            store.save_user("benchmark", "feature-admin", password, "admin", ["market", "catalog"], True, create=True)
            store.save_user("benchmark", "feature-observer", password, "observer", ["market"], True, create=True)
            store.save_user("benchmark", "feature-restricted", password, "observer", ["market"], True, assets=["SYNTHETIC.A"], sources=["*"], create=True)
            admin_token = store.login("feature-admin", password)
            observer_token = store.login("feature-observer", password)
            restricted_token = store.login("feature-restricted", password)

            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "server")])
            command = [
                sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "server"),
                "--host", args.host, "--port", str(args.port), "--log-level", "warning",
            ]
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base_url = f"http://{args.host}:{args.port}"
            wait_ready(process, base_url, args.ready_timeout)
            if read_json(base_url, "/api/features/latest", observer_token, args.timeout) != expected:
                raise AssertionError("HTTP 预热结果与权威快照不一致")
            http_measurement = measure_http_keep_alive(args.host, args.port, observer_token, expected, args.http_samples, args.timeout)
            hits_before = read_json(base_url, "/api/system/feature-cache", admin_token, args.timeout)["validated_hits"]
            restricted_status = request_status(args.host, args.port, "/api/features/latest", restricted_token, args.timeout)
            hits_after = read_json(base_url, "/api/system/feature-cache", admin_token, args.timeout)["validated_hits"]
            restricted_forbidden = restricted_status == 403
            forbidden_before_cache = restricted_forbidden and hits_after == hits_before
            if not forbidden_before_cache:
                raise AssertionError("受限账号未能在缓存读取前被拒绝")
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if second_service is not None:
                second_service.close()
            service.close()
            store_for.cache_clear()

    checks = {
        "real_redis_write_and_hit": True,
        "authoritative_result_consistent": direct["result_consistent"] and http_measurement["result_consistent"],
        "cross_service_object_hit": cross_instance_hit,
        "cache_miss_repopulation": len(miss_durations) == args.miss_samples,
        "ttl_expiry": ttl_expiry,
        "corrupt_envelope_rejected": corrupt_rejected,
        "refused_endpoint_fallback": outage_fallback,
        "circuit_opened": circuit_opened,
        "circuit_recovery": circuit_recovery,
        "restricted_account_forbidden": restricted_forbidden,
        "forbidden_before_cache_read": forbidden_before_cache,
    }
    target_passed = bool(direct["p95_within_target"]) and checks["authoritative_result_consistent"]
    report = {
        "report_type": "redis_feature_cache_performance",
        "performance_version": "redis-feature-cache-performance-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_sha256(),
        "benchmark_source_sha256": benchmark_source_sha256(),
        "complete": True,
        "configuration": {
            "data_profile": "synthetic-e2e",
            "data": "3 synthetic assets, 1000 business days",
            "measurement_path": "MarketService.latest_features -> FeatureSnapshotCache.read -> RedisJsonCache.get",
            "measurement_boundary": "仅生产服务热特征读取；返回值一致性比较在计时外，不含模型初始化、鉴权或 HTTP",
            "http_boundary": "本机单长连接，包含真实 HTTP、JWT/SQLite 鉴权、生产服务读取和 Redis；仅作参考，不替代 101 用户 API 基准",
            "rounds": args.rounds,
            "samples_per_round": args.samples,
            "http_samples": args.http_samples,
            "miss_samples": args.miss_samples,
            "redis_host": args.redis_host,
            "redis_port": args.redis_port,
            "redis_ttl_seconds": 300,
            "namespace_isolated": True,
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "git_revision": os.getenv("MARKETLENS_GIT_REVISION") or git_revision(),
            "redis_version": server_info["redis_version"],
            "redis_mode": server_info.get("redis_mode", "unknown"),
            "resource_usage": "not_collected",
        },
        "measurement": {
            "validated_hit": direct,
            "cache_miss_repopulation": {**summarize_latencies(miss_durations, None), "result_consistent": True},
            "http_keep_alive": http_measurement,
        },
        "checks": checks,
        "target_evaluation": {
            "provisional_latency_statistic": "p95",
            "primary_measurement": "validated_hit",
            "target_p95_ms": 10,
            "redis_feature_p95_below_10ms": target_passed,
            "passes_provisional_target": target_passed,
            "functional_checks_all_passed": all(checks.values()),
            "note": "只判定真实 Redis 的生产服务有效命中路径；HTTP、未命中回填和功能检查单列，不用局部结果外推完整 API 或生产 SLA",
        },
        "limitations": [
            "同机单 Redis 和独立合成数据；不是真实赛题行情的性能结论",
            "跨实例检查使用两个独立 Python 服务对象；不是多进程、多节点或 Nginx 验收",
            "HTTP 参考为单长连接顺序请求；不替代独立用户并发、混合读写或公网测试",
            "故障通过拒绝连接的本机端点注入，未停止 Redis 进程；未测持久化、复制和节点故障",
            "权限使用临时合成账号；未读取正式身份库，未覆盖所有角色和跨服务部署矩阵",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "redis_version": report["environment"]["redis_version"],
        "validated_hit": direct["latency_ms"],
        "cache_miss_repopulation": report["measurement"]["cache_miss_repopulation"]["latency_ms"],
        "http_keep_alive": http_measurement["latency_ms"],
        "checks": checks,
        "passes_provisional_target": target_passed,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
