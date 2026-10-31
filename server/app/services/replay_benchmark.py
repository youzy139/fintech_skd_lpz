from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.observability import percentile

SERVER_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def api_request(opener, base_url: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url + path, data=body, headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{path} 返回 HTTP {error.code}: {detail}") from error


def comparable_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "replay_time"}


def results_close(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(results_close(left[key], right[key], tolerance) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(results_close(a, b, tolerance) for a, b in zip(left, right))
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        if math.isnan(left) and math.isnan(right):
            return True
        return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)
    return type(left) is type(right) and left == right


def result_digest(result: dict[str, Any]) -> str:
    serialized = json.dumps(comparable_result(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def summarize_samples(runs: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [item["total_ms"] for item in runs]
    first = [item["first_result_ms"] for item in runs if item["first_result_ms"] is not None]
    throughput = [item["records_per_second"] for item in runs if item["records_per_second"] is not None]
    return {
        "runs": len(runs),
        "total_ms": {"p50": percentile(elapsed, 0.5), "p95": percentile(elapsed, 0.95), "min": round(min(elapsed), 3) if elapsed else None, "max": round(max(elapsed), 3) if elapsed else None},
        "first_result_ms": {"p50": percentile(first, 0.5), "p95": percentile(first, 0.95)},
        "records_per_second": {"p50": percentile(throughput, 0.5), "p95": percentile(throughput, 0.95)},
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    cold = [item for item in runs if item.get("temperature") == "cold"]
    warm = [item for item in runs if item.get("temperature") == "warm"]
    return {
        **summarize_samples(runs),
        "cold": summarize_samples(cold) if cold else None,
        "warm": summarize_samples(warm) if warm else None,
    }


def run_once(opener, base_url: str, mode: str, start: str, end: str, speed: float, timeout: float, poll_interval: float, run_index: int) -> dict[str, Any]:
    create_started = time.monotonic()
    created = api_request(opener, base_url, "/api/replay/sessions", {"start_date": start, "end_date": end, "speed": speed, "mode": mode})
    create_ms = (time.monotonic() - create_started) * 1000
    session_id = created["id"]
    started = time.monotonic()
    current = api_request(opener, base_url, f"/api/replay/sessions/{session_id}/start", {})
    first_result_ms = None
    days = []
    seen_dates = set()
    deadline = started + timeout
    while time.monotonic() < deadline:
        timing = current.get("timing", {})
        last_day = timing.get("last_day")
        if last_day and last_day["event_date"] not in seen_dates:
            seen_dates.add(last_day["event_date"])
            days.append({"event_date": last_day["event_date"], "input_records": current["latest_result"]["input_records"], "timing": last_day})
        if first_result_ms is None and current.get("processed_days", 0) >= 1 and current.get("latest_result"):
            first_result_ms = (time.monotonic() - started) * 1000
        if current["status"] == "completed":
            break
        if current["status"] == "failed":
            raise RuntimeError(f"{mode} 回放失败: {current.get('error')}")
        time.sleep(poll_interval)
        current = api_request(opener, base_url, f"/api/replay/sessions/{session_id}")
    else:
        raise TimeoutError(f"{mode} 回放在 {timeout} 秒内未完成")
    total_ms = (time.monotonic() - started) * 1000
    record_count = sum(item["input_records"] for item in days)
    complete_days = len(days) == current["total_days"]
    return {
        "run_index": run_index,
        "temperature": "cold" if run_index == 1 else "warm",
        "session_id": session_id,
        "run_id": current.get("run_id"),
        "status": current["status"],
        "create_ms": round(create_ms, 3),
        "first_result_ms": round(first_result_ms, 3) if first_result_ms is not None else None,
        "total_ms": round(total_ms, 3),
        "processed_days": current["processed_days"],
        "observed_records": record_count if complete_days else None,
        "records_per_second": round(record_count / (total_ms / 1000), 3) if complete_days and total_ms > 0 else None,
        "event_stats": current["event_stats"],
        "timing": current["timing"],
        "days": days,
        "final_result": comparable_result(current["latest_result"]),
        "final_result_digest": result_digest(current["latest_result"]),
    }


def git_revision() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="对同一历史区间执行本地、Kafka、Flink 可复现回放基准")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--modes", default="local,kafka,flink")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--speed", type=float, default=10)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1 or args.speed <= 0 or args.timeout <= 0 or args.poll_interval <= 0:
        parser.error("runs、speed、timeout 和 poll-interval 必须为正数")
    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    if not modes or any(item not in {"local", "kafka", "flink"} for item in modes):
        parser.error("modes 只能包含 local、kafka、flink")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    output = args.output or SERVER_ROOT / "data" / "benchmarks" / f"replay-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    results = {}
    failure = None
    try:
        for mode in modes:
            runs = [run_once(opener, args.base_url, mode, args.start, args.end, args.speed, args.timeout, args.poll_interval, index) for index in range(1, args.runs + 1)]
            results[mode] = {"summary": summarize_runs(runs), "runs": runs}
            summary = results[mode]["summary"]
            print(f"{mode}: 整轮 p50={summary['total_ms']['p50']}ms, 首日 p50={summary['first_result_ms']['p50']}ms", file=sys.stderr)
    except Exception as error:
        failure = {"mode": mode, "type": type(error).__name__, "message": str(error)}
        print(f"{mode}: 基准失败: {error}", file=sys.stderr)
    final_results = [run["final_result"] for mode in results.values() for run in mode["runs"]]
    consistent = all(results_close(final_results[0], item) for item in final_results[1:]) if final_results else None
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {"base_url": args.base_url, "start": args.start, "end": args.end, "modes": modes, "runs": args.runs, "speed": args.speed, "timeout_seconds": args.timeout, "poll_interval_seconds": args.poll_interval, "comparison_tolerance": 1e-12},
        "environment": {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(), "git_revision": git_revision(), "resource_usage": "not_collected"},
        "complete": failure is None,
        "failure": failure,
        "final_result_consistent": consistent,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"complete": report["complete"], "failure": failure, "final_result_consistent": report["final_result_consistent"], "summary": {mode: value["summary"] for mode, value in results.items()}, "output": str(output)}, ensure_ascii=False, indent=2))
    if failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
