from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from app.core.auth import auth_store
from app.core.observability import percentile
from app.services.replay_benchmark import git_revision


SCENARIOS = {
    "latest_state": "/api/regimes/latest",
    "assets": "/api/assets",
    "alerts": "/api/alerts?limit=100",
    "catalog_summary": "/api/data/summary",
    "calendar_records": "/api/data/records?limit=20&kind=calendar",
}


def summarize(durations: list[float], statuses: list[int], elapsed: float | None = None) -> dict:
    return {
        "requests": len(statuses),
        "successful": sum(status == 200 for status in statuses),
        "statuses": {str(status): statuses.count(status) for status in sorted(set(statuses))},
        "latency_ms": {name: percentile(durations, quantile) for name, quantile in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99), ("min", 0), ("max", 1))},
        "mean_ms": round(sum(durations) / len(durations), 3) if durations else None,
        "throughput_requests_per_second": round(len(statuses) / elapsed, 3) if elapsed else None,
    }


def call(base_url: str, path: str, token: str, timeout: float) -> tuple[float, int]:
    request = Request(base_url + path, headers={"Accept": "application/json", "Authorization": "Bearer " + token})
    started = time.perf_counter()
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            response.read()
            status = response.status
    except HTTPError as error:
        error.read()
        status = error.code
    return (time.perf_counter() - started) * 1000, status


def execute(base_url: str, path: str, count: int, workers: int, tokens: list[str], timeout: float) -> dict:
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda index: call(base_url, path, tokens[index % len(tokens)], timeout), range(count)))
    elapsed = time.perf_counter() - started
    durations = [item[0] for item in results]
    statuses = [item[1] for item in results]
    return {**summarize(durations, statuses, elapsed), "wall_ms": round(elapsed * 1000, 3), "workers": workers, "p95_within_50ms": percentile(durations, 0.95) < 50}


def main():
    parser = argparse.ArgumentParser(description="MarketLens API 延迟与并发基线；使用三个短期服务身份，不代表独立真实用户")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.samples, args.warmup, args.concurrency) < 1 or args.timeout <= 0:
        parser.error("samples、warmup、concurrency 和 timeout 必须为正数")
    tokens = [auth_store().service_token(name) for name in ("backend", "feature", "alert")]
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {"base_url": args.base_url, "samples": args.samples, "warmup": args.warmup, "concurrency": args.concurrency, "timeout_seconds": args.timeout},
        "environment": {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(), "git_revision": os.getenv("MARKETLENS_GIT_REVISION") or git_revision(), "resource_usage": "collect_with_docker_stats"},
        "identity": {"type": "short_lived_service_jwt", "service_identities": 3, "note": "并发数是同时执行的 HTTP 请求数，不是独立真实用户账号数"},
        "sequential": {},
        "concurrent": {},
    }
    for name, path in SCENARIOS.items():
        for index in range(args.warmup):
            call(args.base_url, path, tokens[index % len(tokens)], args.timeout)
        report["sequential"][name] = execute(args.base_url, path, args.samples, 1, tokens, args.timeout)
        report["concurrent"][name] = execute(args.base_url, path, args.concurrency, args.concurrency, tokens, args.timeout)
        print(json.dumps({"scenario": name, "sequential_p95": report["sequential"][name]["latency_ms"]["p95"], "concurrent_p95": report["concurrent"][name]["latency_ms"]["p95"], "concurrent_statuses": report["concurrent"][name]["statuses"]}, ensure_ascii=False), flush=True)
    output = args.output or Path(__file__).resolve().parents[1] / "data" / "benchmarks" / f"api-performance-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "all_successful": all(item["successful"] == item["requests"] for group in (report["sequential"], report["concurrent"]) for item in group.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
