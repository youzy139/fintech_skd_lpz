"""Read-only comparison of local cluster labels and aligned regime identities."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from market_core.ingestion.assets import AssetRepository
from market_core.models.alerts import generate_alerts
from market_core.models.features import build_market_features
from market_core.models.regime import LEGACY_IDENTITY, REGIME_IDENTITY, WalkForwardRegimeModel
from app.services.replay_benchmark import results_close


def audit(data_root: Path) -> dict:
    config = json.loads((ROOT / "server/config.example.json").read_text(encoding="utf-8"))
    settings = config["model"]
    series, quality = AssetRepository(data_root).load_all()
    features = build_market_features(series, settings["volatility_window"], settings["momentum_window"], settings["analysis_start"])
    parameters = [settings[key] for key in ("minimum_history", "training_window", "refit_interval", "cluster_count", "random_seed")]
    old = WalkForwardRegimeModel(*parameters, LEGACY_IDENTITY).predict(features)
    new = WalkForwardRegimeModel(*parameters, REGIME_IDENTITY).predict(features)
    assert len(old) == len(new)
    for before, after in zip(old, new):
        for key in ("date", "cluster", "trained_through", "features", "contributions"):
            assert results_close(before[key], after[key]), (before["date"], key)
        assert np.isclose(before["confidence"], after["confidence"], atol=1e-12)
    old_alerts = generate_alerts(old, **config["alerts"])
    new_alerts = generate_alerts(new, **config["alerts"])
    before_changes = {item.date for item in old_alerts if item.rule == "REGIME_CHANGE"}
    after_changes = {item.date for item in new_alerts if item.rule == "REGIME_CHANGE"}
    assert [asdict(item) for item in old_alerts if item.rule != "REGIME_CHANGE"] == [asdict(item) for item in new_alerts if item.rule != "REGIME_CHANGE"]
    refits = {new[index]["date"] for index in range(1, len(new)) if new[index]["trained_through"] != new[index - 1]["trained_through"]}
    removed, added = before_changes - after_changes, after_changes - before_changes
    assert (removed | added) <= refits
    differences = []
    for index in range(1, len(new)):
        day = new[index]["date"]
        if day not in removed | added:
            continue
        differences.append({
            "date": day, "refit": day in refits,
            "old_previous": old[index - 1]["label"], "old_current": old[index]["label"],
            "new_previous": new[index - 1]["label"], "new_current": new[index]["label"],
            "old_alert": day in before_changes, "new_alert": day in after_changes,
        })
    source_files = ["market_core/models/regime.py", "market_core/models/alerts.py", "market_core/models/features.py"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files},
        "feature_sha256": hashlib.sha256(pd.util.hash_pandas_object(features, index=True).values.tobytes()).hexdigest(),
        "model_settings": settings, "alert_settings": config["alerts"],
        "quality": asdict(quality), "feature_days": len(features), "state_days": len(new),
        "first_state": new[0]["date"], "last_state": new[-1]["date"], "refit_boundaries": len(refits),
        "old_alerts": dict(Counter(item.rule for item in old_alerts)),
        "new_alerts": dict(Counter(item.rule for item in new_alerts)),
        "removed_change_dates": sorted(removed), "added_change_dates": sorted(added),
        "differences": differences,
        "checks": {"numerical_results_unchanged": True, "quantile_alerts_unchanged": True, "differences_only_at_refit": True},
        "limitations": "中心匹配只修正局部编号身份；新增/减少切换不是金融事件准确率或误报率的证明。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="只读核查真实行情重训簇身份与预警差异，不加载身份库或运行存储")
    parser.add_argument("--data-root", type=Path, default=ROOT / "上科大数据合集")
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/regime-identity.json")
    args = parser.parse_args()
    report = audit(args.data_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("state_days", "refit_boundaries", "old_alerts", "new_alerts", "removed_change_dates", "added_change_dates", "checks")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
