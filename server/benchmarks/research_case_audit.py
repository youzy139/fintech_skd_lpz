"""Generate one deterministic research case from read-only market history."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.services.stability import write_json
from app.services.replay_benchmark import results_close
from market_core.domain.replay import AssetObservation, ReplayDayInput
from market_core.ingestion.assets import AssetRepository
from market_core.models.alerts import alert_evidence, generate_alerts
from market_core.models.feature_contracts import market_input_version
from market_core.models.features import build_market_features
from market_core.models.regime import REGIME_IDENTITY, WalkForwardRegimeModel
from market_core.models.replay import HistoricalMarketReplay
from market_core.models.research import build_research_case, select_research_alert

SOURCE_FILES = (
    "market_core/models/research.py",
    "market_core/models/regime.py",
    "market_core/models/alerts.py",
    "market_core/models/features.py",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="只读生成最近一次状态切换研究案例，不加载运行数据库或目录背景")
    parser.add_argument("--data-root", type=Path, default=ROOT / "上科大数据合集")
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/research-case.json")
    args = parser.parse_args()
    config = json.loads((ROOT / "server/config.example.json").read_text(encoding="utf-8"))
    settings = config["model"]
    series, quality = AssetRepository(args.data_root).load_all()
    features = build_market_features(series, settings["volatility_window"], settings["momentum_window"], settings["analysis_start"])
    states = WalkForwardRegimeModel(
        settings["minimum_history"], settings["training_window"], settings["refit_interval"],
        settings["cluster_count"], settings["random_seed"], settings.get("regime_identity", REGIME_IDENTITY),
    ).predict(features)
    alerts = [item.__dict__ for item in generate_alerts(states, **config["alerts"])]
    selected = select_research_alert(alerts)
    if selected is None:
        raise RuntimeError("真实历史没有可用于研究案例的预警")
    evidence = alert_evidence(states, alerts, str(selected["rule"]), str(selected["date"]), config["alerts"])
    case = build_research_case(evidence)
    replay_start = date.fromisoformat(case["replay"]["start_date"])
    replay_end = date.fromisoformat(case["replay"]["end_date"])
    engine = HistoricalMarketReplay(series, settings, config["alerts"], replay_start)
    replay_days = []
    final_result = None
    event_dates = sorted({day.date() for item in series for day in item.frame["date"] if replay_start <= day.date() <= replay_end})
    for event_day in event_dates:
        observations = tuple(
            AssetObservation(item.meta.code, event_day, float(value))
            for item in series
            for value in item.frame.loc[item.frame["date"] == pd.Timestamp(event_day), "value"]
        )
        final_result = engine.advance(ReplayDayInput(event_day, observations))
        replay_days.append({
            "event_time": final_result.event_time,
            "input_records": final_result.input_records,
            "observed_assets": list(final_result.observed_assets),
            "features": final_result.features,
            "state": final_result.state,
            "alert_rules": [item["rule"] for item in final_result.alerts],
        })
    if final_result is None or not results_close(final_result.state, evidence["state"]):
        replay_state = final_result.state if final_result else None
        keys = set((replay_state or {}).keys()) | set(evidence["state"].keys())
        differences = {
            key: {"replay": (replay_state or {}).get(key), "case": evidence["state"].get(key)}
            for key in keys if not results_close((replay_state or {}).get(key), evidence["state"].get(key))
        }
        raise AssertionError("真实回放末日状态与研究案例不一致：" + json.dumps({"differences": differences, "days": replay_days}, ensure_ascii=False, default=str))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_version": market_input_version(series),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        "loaded_assets": len(series),
        "total_rows": quality.total_rows,
        "state_days": len(states),
        "alert_count": len(alerts),
        "background_context": "not_loaded_in_offline_audit",
        "replay_verification": {
            "mode": "local", "status": "matched", "processed_days": len(replay_days),
            "final_state_matches_case": True, "days": replay_days,
        },
        "limitations": "离线脚本不加载目录背景；页面 API 仍按前一状态日和账号来源范围加载。案例不是人工金融事件标注或投资效果证明。",
        "case": case,
    }
    write_json(args.output, report)
    print(json.dumps({
        "case_id": case["case_id"], "event_time": case["event_time"],
        "rule": evidence["rule"], "state": evidence["state"]["label"],
        "previous_state": evidence["previous_state"]["label"] if evidence["previous_state"] else None,
        "replay": case["replay"], "alert_count": len(alerts),
        "replay_verification": {"status": "matched", "processed_days": len(replay_days)},
    }, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
