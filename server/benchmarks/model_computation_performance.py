"""Measure real single-day feature and walk-forward regime computation without changing results."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.core.observability import percentile
from app.services.model_performance import PERFORMANCE_VERSION, SOURCE_FILES
from app.services.replay import ReplayDataCatalog
from app.services.replay_benchmark import comparable_result, git_revision, result_digest, results_close
from app.services.stability import write_json
from market_core.domain.market import AssetSeries
from market_core.models.feature_contracts import feature_contract, market_input_version, model_parameters
from market_core.models.replay import HistoricalMarketReplay

TARGETS = {"features": 50.0, "regime_non_refit": 1000.0, "regime_refit": 1000.0}


def summarize_latency(values: Sequence[float], target_ms: float) -> dict[str, Any]:
    samples = [float(value) for value in values]
    p95 = percentile(samples, 0.95)
    return {
        "sample_count": len(samples),
        "latency_ms": {
            "p50": percentile(samples, 0.5),
            "p95": p95,
            "p99": percentile(samples, 0.99),
            "min": round(min(samples), 3) if samples else None,
            "max": round(max(samples), 3) if samples else None,
            "mean": round(sum(samples) / len(samples), 3) if samples else None,
        },
        "target_p95_ms": target_ms,
        "p95_within_target": p95 < target_ms if p95 is not None else None,
    }


def summarize_days(days: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups = {
        "features": [item["feature_ms"] for item in days if item.get("feature_ms") is not None],
        "regime_non_refit": [item["regime_ms"] for item in days if item.get("regime_ms") is not None and not item["refit"]],
        "regime_refit": [item["regime_ms"] for item in days if item.get("regime_ms") is not None and item["refit"]],
    }
    summaries = {name: summarize_latency(values, TARGETS[name]) for name, values in groups.items()}
    all_regime = groups["regime_non_refit"] + groups["regime_refit"]
    summaries["regime_all"] = summarize_latency(all_regime, TARGETS["regime_refit"])
    return summaries


def measure_replay_run(
    series: list[AssetSeries],
    model_settings: Mapping[str, Any],
    alert_settings: Mapping[str, Any],
    days: Sequence[date],
    run_index: int,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Observe one call per production stage; initialization and warm-up stay outside daily samples."""
    if not days:
        raise ValueError("性能测量至少需要一个事件日")
    catalog = ReplayDataCatalog(series)
    initialization_started = clock()
    engine = HistoricalMarketReplay(series, dict(model_settings), dict(alert_settings), days[0])
    initialization_ms = (clock() - initialization_started) * 1000
    current: dict[str, Any] = {}
    original_features = engine._calculate_features
    original_predict = engine.model_session.predict_latest

    def timed_features(output_start: str | None = None):
        started = clock()
        result = original_features(output_start)
        current["feature_call_ms"] = (clock() - started) * 1000
        current["feature_calls"] = current.get("feature_calls", 0) + 1
        return result

    def timed_predict(features):
        previous_fitted = engine.model_session.fitted
        started = clock()
        result = original_predict(features)
        current["regime_call_ms"] = (clock() - started) * 1000
        current["regime_calls"] = current.get("regime_calls", 0) + 1
        current["refit"] = previous_fitted is not engine.model_session.fitted
        return result

    engine._calculate_features = timed_features
    engine.model_session.predict_latest = timed_predict
    samples = []
    results = []
    for event_day in days:
        current = {}
        result = engine.advance(catalog.read(event_day))
        if current.get("feature_calls") != 1 or current.get("regime_calls", 0) > 1:
            raise RuntimeError("性能探针检测到单日计算调用次数异常")
        has_features = bool(result.features)
        has_state = result.state is not None
        if has_state and not has_features:
            raise RuntimeError("状态结果缺少对应的有效特征")
        samples.append({
            "event_date": event_day.isoformat(),
            "feature_ms": round(current["feature_call_ms"], 3) if has_features else None,
            "regime_ms": round(current["regime_call_ms"], 3) if has_state else None,
            "feature_calls": current["feature_calls"],
            "regime_calls": current.get("regime_calls", 0),
            "valid_feature": has_features,
            "state_generated": has_state,
            "refit": bool(current.get("refit", False)) if has_state else None,
            "trained_through": result.state.get("trained_through") if has_state else None,
            "result_digest": result_digest(asdict(result)),
        })
        results.append(result)
    return {
        "run_index": run_index,
        "temperature": "first_engine_in_process" if run_index == 1 else "subsequent_engine_in_process",
        "initialization_ms_excluded_from_daily_samples": round(initialization_ms, 3),
        "days": samples,
        "summary": summarize_days(samples),
        "final_result": asdict(results[-1]),
        "daily_results": [asdict(result) for result in results],
        "result_digests": [sample["result_digest"] for sample in samples],
    }


def build_performance_report(
    series: list[AssetSeries],
    model_settings: Mapping[str, Any],
    alert_settings: Mapping[str, Any],
    days: Sequence[date],
    runs: int = 3,
    data_profile: str = "unspecified",
) -> dict[str, Any]:
    if runs < 1:
        raise ValueError("重复轮次必须为正数")
    measurements = [measure_replay_run(series, model_settings, alert_settings, days, index) for index in range(1, runs + 1)]
    reference = measurements[0]["result_digests"]
    reference_results = [comparable_result(item) for item in measurements[0]["daily_results"]]
    consistent = all(
        results_close(reference, comparable_result(candidate))
        for run in measurements[1:]
        for reference, candidate in zip(reference_results, run["daily_results"])
    )
    exact_matching_days = sum(
        all(run["result_digests"][index] == digest for run in measurements[1:])
        for index, digest in enumerate(reference)
    )
    for run in measurements:
        del run["daily_results"]
    all_days = [day for run in measurements for day in run["days"]]
    summary = summarize_days(all_days)
    source_sha256 = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    benchmark_source_sha256 = hashlib.sha256((ROOT / "server/benchmarks/model_computation_performance.py").read_bytes()).hexdigest()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *SOURCE_FILES, "server/benchmarks/model_computation_performance.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    computation_sources_dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return {
        "report_type": "model_computation_performance",
        "performance_version": PERFORMANCE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "measurement_errors": [],
        "result_consistent": consistent,
        "result_comparison": {
            "method": "numeric_tolerance_1e-12_excluding_replay_time",
            "compared_days_per_run": len(reference),
            "exact_digest_matching_days": exact_matching_days,
        },
        "targets_conclusive": consistent,
        "input_version": market_input_version(series),
        "feature_version": feature_contract(dict(model_settings))["feature_version"],
        "model_parameters": model_parameters(dict(model_settings)),
        "source_sha256": source_sha256,
        "benchmark_source_sha256": benchmark_source_sha256,
        "configuration": {
            "event_start": days[0].isoformat(),
            "event_end": days[-1].isoformat(),
            "event_days_per_run": len(days),
            "runs": runs,
            "loaded_assets": len(series),
            "data_profile": data_profile,
            "input_rows": sum(len(item.frame) for item in series),
            "statistic": "p95_with_p50_p99_min_max_mean",
            "measurement_boundary": "生产 HistoricalMarketReplay.advance 内各一次真实特征/状态调用；不含历史预热、输入追加、预警和持久化",
            "temperature_boundary": "首轮与后续新建 engine 均在同进程；不是冷进程或跨机器结论",
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "git_revision": git_revision(),
            "computation_sources_dirty_at_generation": computation_sources_dirty,
            "resource_usage": "not_collected",
        },
        "summary": summary,
        "runs": measurements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="只读真实行情的单日特征与状态识别性能基准，不加载运行数据库")
    parser.add_argument("--data-root", type=Path, default=ROOT / "上科大数据合集")
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/model-computation-performance.json")
    parser.add_argument("--days", type=int, default=63)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    if args.days < 1 or args.runs < 1 or bool(args.start) != bool(args.end):
        parser.error("days、runs 必须为正数，start 和 end 必须同时提供")
    from market_core.ingestion.assets import AssetRepository

    config = json.loads((ROOT / "server/config.example.json").read_text(encoding="utf-8"))
    series, _ = AssetRepository(args.data_root).load_all()
    catalog = ReplayDataCatalog(series)
    if args.start and args.end:
        days = catalog.dates_between(date.fromisoformat(args.start), date.fromisoformat(args.end))
    else:
        days = catalog.dates[-args.days:]
    failure = None
    try:
        report = build_performance_report(series, config["model"], config["alerts"], days, args.runs, data_profile="real-competition-read-only")
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
        report = {
            "report_type": "model_computation_performance",
            "performance_version": PERFORMANCE_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "complete": False,
            "measurement_errors": [failure],
            "targets_conclusive": False,
            "configuration": {"event_start": days[0].isoformat(), "event_end": days[-1].isoformat(), "runs": args.runs},
        }
    write_json(args.output, report)
    print(json.dumps({
        "complete": report["complete"],
        "result_consistent": report.get("result_consistent"),
        "summary": report.get("summary"),
        "failure": failure,
        "output": str(args.output),
    }, ensure_ascii=False, allow_nan=False))
    if failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
