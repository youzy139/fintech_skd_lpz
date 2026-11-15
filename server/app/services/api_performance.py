from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PERFORMANCE_VERSION = "independent-user-api-performance-v1"
ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = (
    "server/app/core/auth.py",
    "server/app/core/config.py",
    "server/app/core/governance.py",
    "server/app/core/observability.py",
    "server/app/main.py",
    "server/app/data_service.py",
    "server/app/alert_service.py",
    "server/app/api/market.py",
    "server/app/api/data.py",
    "server/app/services/cache.py",
    "server/app/services/catalog.py",
    "server/app/services/market.py",
)


def source_sha256() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def performance_report_path(database_path: Path) -> Path:
    return database_path.parent / "benchmarks" / "independent-users.json"


def catalog_version_report_path(database_path: Path) -> Path:
    return database_path.parent / "benchmarks" / "catalog-version-performance.json"


def load_api_performance_report(database_path: Path) -> dict[str, Any]:
    path = performance_report_path(database_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("尚未生成独立用户 API 性能报告，请先运行隔离基准脚本") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("独立用户 API 性能报告不可读取，请重新生成") from error
    if (
        report.get("report_type") != "independent_user_api_performance"
        or report.get("performance_version") != PERFORMANCE_VERSION
        or report.get("source_sha256") != source_sha256()
    ):
        raise ValueError("独立用户 API 性能报告与当前运行源码不匹配，请重新生成")
    catalog_path = catalog_version_report_path(database_path)
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        catalog = None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("目录数据版本性能报告不可读取，请重新生成") from error
    if catalog is not None:
        expected_environment = {key: report.get("environment", {}).get(key) for key in ("platform", "python", "cpu_count")}
        if (
            catalog.get("performance_version") != "catalog-version-performance-v1"
            or catalog.get("catalog_source_sha256") != hashlib.sha256((ROOT / "server/app/services/catalog.py").read_bytes()).hexdigest()
            or any(catalog.get("environment", {}).get(key) != value for key, value in expected_environment.items())
        ):
            raise ValueError("目录数据版本性能报告与当前目录源码或运行环境不匹配，请重新生成")
        report["catalog_version_performance"] = catalog
    return report
