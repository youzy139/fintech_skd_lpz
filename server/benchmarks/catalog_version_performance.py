from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.core.config import load_config
from app.core.observability import percentile
from app.services.replay_benchmark import git_revision

QUERY = "SELECT id, size, mtime_ns, status, record_count, error_count, updated_at FROM source_files ORDER BY id"


def full_version(connection: sqlite3.Connection) -> str:
    rows = connection.execute(QUERY).fetchall()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def cached_version(connection: sqlite3.Connection, cache: list) -> str:
    revision = connection.execute("PRAGMA data_version").fetchone()[0]
    if cache and cache[0] == revision:
        return cache[1]
    version = full_version(connection)
    cache[:] = [revision, version]
    return version


def summary(values: list[float]) -> dict:
    return {
        "sample_count": len(values),
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
        "mean_ms": round(sum(values) / len(values), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="真实 SQLite 只读目录数据版本微基准；不是 HTTP 或生产 SLA")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/catalog-version-performance.json")
    args = parser.parse_args()
    if args.samples < 1 or args.warmup < 1:
        parser.error("samples 和 warmup 必须为正数")
    database = (args.database or load_config().database_path).resolve()
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        source_files = connection.execute("SELECT count(*) FROM source_files").fetchone()[0]
        if not source_files:
            raise ValueError("目录没有 source_files，无法测量")
        expected = full_version(connection)
        cache: list = []
        for _ in range(args.warmup):
            full_version(connection)
            cached_version(connection, cache)
        legacy_times: list[float] = []
        cached_times: list[float] = []
        for index in range(args.samples):
            methods = ((full_version, legacy_times), (cached_version, cached_times)) if index % 2 == 0 else ((cached_version, cached_times), (full_version, legacy_times))
            for method, durations in methods:
                started = time.perf_counter()
                if method is cached_version:
                    value = method(connection, cache)
                else:
                    value = method(connection)
                durations.append((time.perf_counter() - started) * 1000)
                if value != expected:
                    raise RuntimeError("目录数据版本结果不一致")
        legacy = summary(legacy_times)
        cached = summary(cached_times)
        delta = round(legacy["mean_ms"] - cached["mean_ms"], 3)
        report = {
            "performance_version": "catalog-version-performance-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "unchanged-sqlite-data-version-read-only-microbenchmark",
            "source_files": source_files,
            "samples_per_path": args.samples,
            "warmup_per_path": args.warmup,
            "measurement_order": "alternating-path-order-on-one-read-only-connection",
            "legacy_full_scans_during_samples": args.samples,
            "cached_full_scans_during_samples": 0,
            "cached_pragma_queries_during_samples": args.samples,
            "initial_cached_full_scan": "在预热中执行一次；不在稳态样本内重复",
            "legacy": legacy,
            "cached": cached,
            "mean_delta_ms": delta,
            "mean_reduction_percent": round(delta / legacy["mean_ms"] * 100, 3) if legacy["mean_ms"] else None,
            "environment": {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(), "git_revision": git_revision()},
            "catalog_source_sha256": hashlib.sha256((ROOT / "server/app/services/catalog.py").read_bytes()).hexdigest(),
            "limitations": "只测未变化 SQLite 数据版本查询路径；不含锁、HTTP、JSON、权限、Redis、并发或导入失效，不是端到端性能结论",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(args.output), "source_files": source_files, "legacy": legacy, "cached": cached, "mean_reduction_percent": report["mean_reduction_percent"]}, ensure_ascii=False))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
