"""Real Redis DNS-loss and circuit-recovery drill for an isolated application.

The Redis container is stopped and renamed, never deleted. A new container with
the original name restores DNS. Use only disposable application/Redis containers.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


OPENER = build_opener(ProxyHandler({}))


def api(base_url: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any], dict[str, str], float]:
    request = Request(base_url + path, data=None if payload is None else json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    started = time.monotonic()
    try:
        response = OPENER.open(request, timeout=90)
    except HTTPError as error:
        response = error
    with response:
        body = json.load(response)
        return response.status, body, {key.lower(): value for key, value in response.headers.items()}, time.monotonic() - started


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18020")
    parser.add_argument("--redis-container", default="marketlens-replay-fault-v034-redis")
    parser.add_argument("--network", default="marketlens-stage-e_marketlens")
    parser.add_argument("--recovery-seconds", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    offline_name = args.redis_container + "-offline-" + str(time.time_ns())
    report: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "redis_dns_removed": False}
    restored = False
    try:
        status, baseline, _, baseline_seconds = api(args.base_url, "/api/data/summary")
        assert status == 200
        report["baseline"] = {"records": baseline["total_records"], "seconds": round(baseline_seconds, 3)}
        docker("stop", "-t", "0", args.redis_container)
        docker("rename", args.redis_container, offline_name)
        report["redis_dns_removed"] = True
        reads = []
        for _ in range(4):
            status, body, headers, elapsed = api(args.base_url, "/api/data/summary")
            assert status == 200 and body["total_records"] == baseline["total_records"]
            reads.append({"seconds": round(elapsed, 3), "rate_limit_mode": headers.get("x-ratelimit-mode")})
        report["reads_during_outage"] = reads
        status, error, _, elapsed = api(args.base_url, "/api/replay/sessions", {"start_date": "2026-04-27", "end_date": "2026-04-27", "speed": 1, "mode": "local"})
        assert status == 503 and error["error"]["code"] == "rate_limit_unavailable"
        report["write_during_outage"] = {"status": status, "code": error["error"]["code"], "seconds": round(elapsed, 3)}
        status, monitoring, _, _ = api(args.base_url, "/api/system/dependencies")
        assert status == 200
        report["open_state"] = {
            "governance": monitoring["governance"]["circuit"],
            "cache": monitoring.get("catalog_cache", {}).get("circuit"),
            "redis_probe": next(item for item in monitoring["checks"] if item["name"] == "redis"),
        }
        assert monitoring["governance"]["circuit"]["state"] == "open"
        assert monitoring["catalog_cache"]["circuit"]["state"] == "open"
        docker("run", "-d", "--name", args.redis_container, "--network", args.network, "redis:8.0.5-alpine")
        restored = True
        time.sleep(args.recovery_seconds + 1)
        status, recovered, headers, elapsed = api(args.base_url, "/api/data/summary")
        assert status == 200 and recovered["total_records"] == baseline["total_records"]
        report["recovery_read"] = {"seconds": round(elapsed, 3), "rate_limit_mode": headers.get("x-ratelimit-mode")}
        status, monitoring, _, _ = api(args.base_url, "/api/system/dependencies")
        assert status == 200
        report["recovered_state"] = {
            "governance": monitoring["governance"]["circuit"],
            "cache": monitoring.get("catalog_cache", {}).get("circuit"),
            "redis_probe": next(item for item in monitoring["checks"] if item["name"] == "redis"),
        }
        assert monitoring["governance"]["circuit"]["state"] == "closed"
        assert monitoring["catalog_cache"]["circuit"]["state"] == "closed"
        assert report["recovered_state"]["redis_probe"]["status"] == "ok"
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
        if report["redis_dns_removed"] and not restored:
            try:
                docker("rename", offline_name, args.redis_container)
                docker("start", args.redis_container)
            except Exception:
                pass
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
