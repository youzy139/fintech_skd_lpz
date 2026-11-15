from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

PERFORMANCE_VERSION = "model-computation-performance-v1"
ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = (
    "market_core/models/features.py",
    "market_core/models/regime.py",
    "market_core/models/replay.py",
)


def performance_report_path(database_path: Path) -> Path:
    return database_path.parent / "benchmarks" / "model-computation-performance.json"


def load_performance_report(database_path: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    path = performance_report_path(database_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("尚未生成单日计算性能报告，请先运行只读基准脚本") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("单日计算性能报告不可读取，请重新生成") from error
    expected = {
        "performance_version": PERFORMANCE_VERSION,
        "input_version": metadata.get("input_version"),
        "feature_version": metadata.get("feature_contract", {}).get("feature_version"),
        "model_parameters": metadata.get("model_parameters"),
    }
    current_sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    stale = (
        report.get("report_type") != "model_computation_performance"
        or any(report.get(key) != value for key, value in expected.items())
        or report.get("source_sha256") != current_sources
    )
    if stale:
        raise ValueError("单日计算性能报告与当前输入、特征、模型或计算源码不匹配，请重新生成")
    return report
