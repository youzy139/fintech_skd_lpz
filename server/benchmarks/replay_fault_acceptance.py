"""Real Kafka/Flink fault drills against an isolated replay service.

Run with PYTHONUTF8=1. The target service must use disposable replay storage;
the original competition data remains read-only. Docker restart/kill affect only
the explicitly named broker and isolated application containers.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


OPENER = build_opener(ProxyHandler({}))


def api(base_url: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 120) -> dict[str, Any]:
    request = Request(
        base_url + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with OPENER.open(request, timeout=timeout) as response:
        return json.load(response)


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, text=True)


def wait_for(call, predicate, timeout: float = 300, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        try:
            latest = call()
            if predicate(latest):
                return latest
        except (OSError, URLError):
            pass
        time.sleep(interval)
    raise TimeoutError(f"condition not met; latest={latest}")


def jobs(flink_url: str) -> list[dict[str, Any]]:
    return api(flink_url, "/jobs/overview").get("jobs", [])


def active_jobs(flink_url: str, session_id: str, run_id: str) -> list[dict[str, Any]]:
    name = f"MarketLens event-time daily windows {session_id}/{run_id}"
    return [item for item in jobs(flink_url) if item.get("name") == name and item.get("state") not in {"CANCELED", "FAILED", "FINISHED"}]


def kafka_restart(args) -> dict[str, Any]:
    created = api(args.base_url, "/api/replay/sessions", {"start_date": "2026-04-27", "end_date": "2026-04-29", "speed": 10, "mode": "kafka"})
    session_id = created["id"]
    api(args.base_url, f"/api/replay/sessions/{session_id}/start", {})
    first = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"), lambda item: item["processed_days"] >= 1 or item["status"] == "failed")
    assert first["status"] != "failed", first["error"]
    started = time.monotonic()
    docker("restart", "-t", "5", args.kafka_container)
    restart_seconds = time.monotonic() - started
    final = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"), lambda item: item["status"] in {"completed", "failed"})
    saved = api(args.base_url, f"/api/replay/sessions/{session_id}/results?after=0&limit=100")["results"]
    result = {
        "scenario": "kafka_broker_restart",
        "session_id": session_id,
        "before_restart": {"status": first["status"], "processed_days": first["processed_days"]},
        "broker_restart_seconds": round(restart_seconds, 3),
        "final": {"status": final["status"], "processed_days": final["processed_days"], "error": final["error"], "event_stats": final["event_stats"]},
        "results": [{"sequence": item["sequence"], "event_date": item["event_date"]} for item in saved],
    }
    result["passed"] = final["status"] == "completed" and [item["sequence"] for item in saved] == [1, 2, 3]
    return result


def flink_crash(args) -> dict[str, Any]:
    if args.session_id:
        session_id = args.session_id
        first = api(args.base_url, f"/api/replay/sessions/{session_id}")
        old_job_id = first["flink_job_id"]
        run_id = first["run_id"]
        orphaned = wait_for(lambda: jobs(args.flink_url), lambda items: any(item.get("jid") == old_job_id and item.get("state") == "RUNNING" for item in items), timeout=30)
    else:
        created = api(args.base_url, "/api/replay/sessions", {"start_date": "2026-04-27", "end_date": "2026-04-29", "speed": 1, "mode": "flink"})
        session_id = created["id"]
        api(args.base_url, f"/api/replay/sessions/{session_id}/start", {})
        first = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"), lambda item: item["processed_days"] >= 1 or item["status"] == "failed")
        assert first["status"] != "failed", first["error"]
        old_job_id = first["flink_job_id"]
        run_id = first["run_id"]
        docker("kill", args.app_container)
        orphaned = wait_for(lambda: jobs(args.flink_url), lambda items: any(item.get("jid") == old_job_id and item.get("state") == "RUNNING" for item in items), timeout=30)
        docker("start", args.app_container)
        wait_for(lambda: api(args.base_url, "/api/health/ready"), lambda item: bool(item), timeout=240, interval=2)
    recovered = api(args.base_url, f"/api/replay/sessions/{session_id}")
    api(args.base_url, f"/api/replay/sessions/{session_id}/resume", {})
    resumed = wait_for(
        lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"),
        lambda item: item.get("flink_job_id") not in {None, old_job_id} or item["status"] == "failed",
    )
    assert resumed["status"] != "failed", resumed["error"]
    during_recovery = active_jobs(args.flink_url, session_id, run_id)
    final = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"), lambda item: item["status"] in {"completed", "failed"})
    remaining = wait_for(
        lambda: active_jobs(args.flink_url, session_id, run_id),
        lambda items: all(item["jid"] != final.get("flink_job_id") for item in items),
        timeout=90,
    )
    final = api(args.base_url, f"/api/replay/sessions/{session_id}")
    saved = api(args.base_url, f"/api/replay/sessions/{session_id}/results?after=0&limit=100")["results"]
    result = {
        "scenario": "flink_process_crash",
        "session_id": session_id,
        "run_id": run_id,
        "old_job_id": old_job_id,
        "orphan_running_after_kill": any(item.get("jid") == old_job_id and item.get("state") == "RUNNING" for item in orphaned),
        "recovered_status": recovered["status"],
        "new_job_id": resumed.get("flink_job_id"),
        "active_jobs_during_recovery": [{"job_id": item["jid"], "state": item["state"]} for item in during_recovery],
        "final": {"status": final["status"], "processed_days": final["processed_days"], "error": final["error"], "event_stats": final["event_stats"], "savepoint_path": final.get("savepoint_path")},
        "active_jobs_after_completion": [{"job_id": item["jid"], "state": item["state"]} for item in remaining],
        "results": [{"sequence": item["sequence"], "event_date": item["event_date"]} for item in saved],
    }
    result["passed"] = (
        final["status"] == "completed"
        and [item["sequence"] for item in saved] == [1, 2, 3]
        and not remaining
        and all(item["jid"] != old_job_id for item in during_recovery)
    )
    return result


def flink_lease_loss(args) -> dict[str, Any]:
    created = api(args.base_url, "/api/replay/sessions", {"start_date": "2026-04-27", "end_date": "2026-05-08", "speed": 1, "mode": "flink"})
    session_id = created["id"]
    api(args.base_url, f"/api/replay/sessions/{session_id}/start", {})
    first = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"), lambda item: item["processed_days"] >= 1 or item["status"] == "failed")
    assert first["status"] != "failed", first["error"]
    job_id = first["flink_job_id"]
    run_id = first["run_id"]
    docker("stop", "-t", "0", args.redis_container)
    try:
        paused = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"), lambda item: item["status"] == "paused", timeout=90)
        remaining_after_loss = wait_for(lambda: active_jobs(args.flink_url, session_id, run_id), lambda items: all(item["jid"] != job_id for item in items), timeout=90)
    finally:
        docker("start", args.redis_container)
    resumed = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}/resume", {}), lambda item: item["status"] == "running", timeout=90)
    final = wait_for(lambda: api(args.base_url, f"/api/replay/sessions/{session_id}"), lambda item: item["status"] in {"completed", "failed"})
    remaining = wait_for(
        lambda: active_jobs(args.flink_url, session_id, run_id),
        lambda items: all(item["jid"] != final.get("flink_job_id") for item in items),
        timeout=90,
    )
    final = api(args.base_url, f"/api/replay/sessions/{session_id}")
    saved = api(args.base_url, f"/api/replay/sessions/{session_id}/results?after=0&limit=100")["results"]
    result = {
        "scenario": "flink_lease_loss",
        "session_id": session_id,
        "run_id": run_id,
        "job_id": job_id,
        "paused": {"processed_days": paused["processed_days"], "error": paused["error"]},
        "job_stopped_after_lease_loss": all(item["jid"] != job_id for item in remaining_after_loss),
        "resumed_job_id": final.get("flink_job_id"),
        "final_status": final["status"],
        "total_days": final["total_days"],
        "active_jobs_after_completion": remaining,
        "results": [{"sequence": item["sequence"], "event_date": item["event_date"]} for item in saved],
    }
    sequences = [item["sequence"] for item in saved]
    result["passed"] = result["job_stopped_after_lease_loss"] and final["status"] == "completed" and not remaining and sequences == list(range(1, final["total_days"] + 1))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["kafka-restart", "flink-crash", "flink-lease-loss"])
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--flink-url", default="http://127.0.0.1:8081")
    parser.add_argument("--app-container", default="marketlens-replay-fault-baseline")
    parser.add_argument("--kafka-container", default="marketlens-stage-e-kafka-1")
    parser.add_argument("--redis-container", default="marketlens-replay-fault-redis")
    parser.add_argument("--session-id", help="Resume an interrupted crash drill instead of creating and killing a new session")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    failure = None
    result = None
    try:
        if args.scenario == "kafka-restart":
            result = kafka_restart(args)
        elif args.scenario == "flink-crash":
            result = flink_crash(args)
        else:
            result = flink_lease_loss(args)
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(time.monotonic() - started, 3), "result": result, "failure": failure}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failure or not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
