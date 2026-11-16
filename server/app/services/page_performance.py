from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PERFORMANCE_VERSION = "browser-page-performance-v1"
ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = (
    "server/app/api/market.py",
    "server/app/api/system.py",
    "server/app/core/auth.py",
    "server/app/main.py",
    "server/app/services/api_performance.py",
    "server/app/services/feature_cache_performance.py",
    "server/app/services/market.py",
    "server/app/services/model_performance.py",
    "server/benchmarks/e2e_server.py",
    "server/benchmarks/page_performance.py",
    "web/playwright.config.ts",
    "web/scripts/page-performance.mjs",
    "web/src/App.tsx",
    "web/src/Auth.tsx",
    "web/src/Landing.tsx",
    "web/src/Workspace.tsx",
    "web/src/MarketOverview.tsx",
    "web/src/RegimeAnalysis.tsx",
    "web/src/RegimeStability.tsx",
    "web/src/FeatureAnalysis.tsx",
    "web/src/AlertCenter.tsx",
    "web/src/ReplayCenter.tsx",
    "web/src/SourceCatalog.tsx",
    "web/src/SystemStatus.tsx",
    "web/src/ApiPerformancePanel.tsx",
    "web/src/ComputationPerformancePanel.tsx",
    "web/src/FeatureCachePerformancePanel.tsx",
    "web/src/PagePerformancePanel.tsx",
    "web/src/EChartsCanvas.tsx",
    "web/src/Chart.tsx",
    "web/src/RegimeChart.tsx",
    "web/src/api.ts",
    "web/src/navigation.ts",
    "web/src/ui.tsx",
    "web/src/research.css",
    "web/vite.config.ts",
)


def source_sha256() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def performance_report_path(database_path: Path) -> Path:
    return database_path.parent / "benchmarks" / "page-performance.json"


def load_page_performance_report(database_path: Path) -> dict[str, Any]:
    path = performance_report_path(database_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("尚未生成页面加载性能报告，请先运行隔离真实 Chrome 基准脚本") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("页面加载性能报告不可读取，请重新生成") from error
    if (
        report.get("report_type") != "browser_page_performance"
        or report.get("performance_version") != PERFORMANCE_VERSION
        or report.get("source_sha256") != source_sha256()
    ):
        raise ValueError("页面加载性能报告与当前页面、接口或基准源码不匹配，请重新生成")
    return report
