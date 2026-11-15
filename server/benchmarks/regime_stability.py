"""Generate a read-only, reproducible walk-forward stability report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.services.stability import build_stability_report, write_stability_bundle
from market_core.ingestion.assets import AssetRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="只读评估训练窗口、重训间隔和随机种子的状态稳定性，不加载运行数据库")
    parser.add_argument("--data-root", type=Path, default=ROOT / "上科大数据合集")
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/regime-stability.json")
    args = parser.parse_args()
    settings = json.loads((ROOT / "server/config.example.json").read_text(encoding="utf-8"))["model"]
    series, quality = AssetRepository(args.data_root).load_all()
    report, daily = build_stability_report(series, settings, catalog_missing_assets=quality.missing_assets)
    report["input_quality"] = {
        "available_assets": quality.available_assets,
        "loaded_assets": quality.loaded_assets,
        "total_rows": quality.total_rows,
        "invalid_rows": quality.invalid_rows,
        "missing_assets": quality.missing_assets,
    }
    write_stability_bundle(report, daily, args.output)
    print(json.dumps({
        "evaluation_id": report["evaluation_id"],
        "run_count": report["grid"]["run_count"],
        "feature_days": report["feature_days"],
        "summary": report["summary"],
        "output": args.output.name,
    }, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
