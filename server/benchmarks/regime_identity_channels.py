"""Exercise the three real transports using synthetic data and isolated topics."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sys
from uuid import uuid4

import numpy as np
import pandas as pd
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.services.flink import FlinkReplayPipeline
from app.services.kafka import KafkaReplayPipeline
from app.services.replay import LocalReplayPipeline, ReplayDataCatalog
from app.services.replay_benchmark import comparable_result, results_close
from market_core.domain.market import AssetMeta, AssetSeries
from market_core.models.alerts import generate_alerts
from market_core.models.features import build_market_features
from market_core.models.regime import REGIME_IDENTITY, WalkForwardRegimeModel
from market_core.models.replay import HistoricalMarketReplay


async def run(broker: str, flink_url: str) -> dict:
    dates = pd.bdate_range("2020-01-01", periods=260)
    series = []
    for index in range(3):
        code = f"SYNTHETIC.{index}"
        values = 100 + index * 20 + np.arange(len(dates)) * 0.03 + np.sin(np.arange(len(dates)) / (5 + index)) * (2 + index)
        meta = AssetMeta("合成验收", code, code, "close", "工作日", dates[0].date(), dates[-1].date(), len(dates), Path(code))
        series.append(AssetSeries(meta, pd.DataFrame({"date": dates, "value": values})))
    model_settings = {"analysis_start": "2020-01-01", "minimum_history": 60, "training_window": 120, "refit_interval": 3, "volatility_window": 20, "momentum_window": 60, "cluster_count": 3, "random_seed": 42}
    alert_settings = {"volatility_quantile": 0.9, "correlation_quantile": 0.9}
    features = build_market_features(series, 20, 60, "2020-01-01")
    states = WalkForwardRegimeModel(60, 120, 3, 3, 42).predict(features)
    baseline_states = {state["date"]: state for state in states}
    baseline_alerts = [asdict(item) for item in generate_alerts(states, **alert_settings)]
    days = tuple(day.date() for day in features.index[68:72])
    catalog = ReplayDataCatalog(series)
    token = "regime-identity-" + uuid4().hex[:12]
    topics = [token + suffix for suffix in ("-input", "-output", "-late")]
    admin = AIOKafkaAdminClient(bootstrap_servers=broker)
    await admin.start()
    try:
        await admin.create_topics([NewTopic(name, 1, 1) for name in topics])
    finally:
        await admin.close()
    kafka = {"enabled": True, "bootstrap_servers": broker, "topic": topics[0], "consumer_max_retries": 3, "retry_backoff_ms": 200}
    flink = {"enabled": True, "rest_url": flink_url, "output_topic": topics[1], "late_topic": topics[2], "checkpoint_interval_ms": 5000, "checkpoint_dir": "file:///tmp/marketlens-flink-checkpoints", "request_timeout_seconds": 10, "job_start_timeout_ms": 90000, "job_stop_timeout_ms": 60000}
    results = {}
    for mode in ("local", "kafka", "flink"):
        session_id = token + "-" + mode
        if mode == "local":
            pipeline = LocalReplayPipeline(days, catalog)
        elif mode == "kafka":
            pipeline = KafkaReplayPipeline(session_id, days, catalog, kafka)
        else:
            settings = {**kafka, "topic": topics[1], "produce_topic": topics[0], "read_committed": True, "emit_end_of_input": True}
            pipeline = FlinkReplayPipeline(session_id, days, catalog, settings, flink)
        engine = HistoricalMarketReplay(series, model_settings, alert_settings, days[0])
        daily = []
        try:
            await asyncio.wait_for(pipeline.start(), timeout=120)
            for day in days:
                batch = await asyncio.wait_for(pipeline.next(day), timeout=60)
                output = comparable_result(asdict(engine.advance(batch)))
                assert results_close(output["state"], baseline_states[day.isoformat()])
                assert results_close(list(output["alerts"]), [item for item in baseline_alerts if item["date"] == day.isoformat()])
                assert output["state"]["regime_identity"] == REGIME_IDENTITY
                await pipeline.ack(batch)
                daily.append(output)
        finally:
            await asyncio.wait_for(pipeline.close(), timeout=90)
        results[mode] = {"days": daily, "stats": pipeline.stats, "savepoint": getattr(pipeline, "savepoint_path", None)}
        print(json.dumps({"mode": mode, "days": len(daily), "passed": True}), flush=True)
    assert results_close(results["local"]["days"], results["kafka"]["days"])
    assert results_close(results["local"]["days"], results["flink"]["days"])
    assert results["flink"]["savepoint"]
    return {"passed": True, "data": "synthetic-only", "topics": topics, "days": [day.isoformat() for day in days], "model_settings": model_settings, "results": results, "limitation": "四日正确性与实际通道验收，不是性能或故障恢复报告。"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="kafka:9092")
    parser.add_argument("--flink-url", default="http://jobmanager:8081")
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/regime-identity-channels.json")
    args = parser.parse_args()
    report = asyncio.run(run(args.broker, args.flink_url))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "days": report["days"]}))


if __name__ == "__main__":
    main()
