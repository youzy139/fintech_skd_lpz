from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PERFORMANCE_VERSION = "redis-feature-cache-performance-v1"
ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = (
    "server/app/api/market.py",
    "server/app/core/auth.py",
    "server/app/core/config.py",
    "server/app/main.py",
    "server/app/services/cache.py",
    "server/app/services/feature_cache.py",
    "server/app/services/market.py",
)
BENCHMARK_SOURCE = "server/benchmarks/feature_cache_performance.py"


def source_sha256() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def benchmark_source_sha256() -> str:
    return hashlib.sha256((ROOT / BENCHMARK_SOURCE).read_bytes()).hexdigest()


def performance_report_path(database_path: Path) -> Path:
    return database_path.parent / "benchmarks" / "feature-cache-performance.json"


def load_feature_cache_performance_report(database_path: Path) -> dict[str, Any]:
    path = performance_report_path(database_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("尚未生成 Redis 热特征性能报告，请先运行隔离真实 Redis 基准脚本") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Redis 热特征性能报告不可读取，请重新生成") from error
    if (
        report.get("report_type") != "redis_feature_cache_performance"
        or report.get("performance_version") != PERFORMANCE_VERSION
        or report.get("source_sha256") != source_sha256()
        or report.get("benchmark_source_sha256") != benchmark_source_sha256()
    ):
        raise ValueError("Redis 热特征性能报告与当前运行源码或基准脚本不匹配，请重新生成")
    return report
