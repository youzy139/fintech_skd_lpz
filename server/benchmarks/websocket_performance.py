from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

from app.core.auth import outgoing_auth_headers
from app.core.observability import percentile
from app.services.feature_proxy import websocket_url
from app.services.replay_benchmark import api_request, git_revision


async def run_once(base_url: str, start: str, end: str, run_index: int) -> dict:
    created = api_request(None, base_url, "/api/replay/sessions", {"start_date": start, "end_date": end, "speed": 10, "mode": "local"})
    session_id = created["id"]
    path = f"/api/replay/sessions/{session_id}"
    url = websocket_url(base_url, f"/ws/replay/{session_id}", "")
    connected = time.perf_counter()
    push_latencies = []
    sequences = []
    async with websockets.connect(url, additional_headers=outgoing_auth_headers(), proxy=None, open_timeout=10) as socket:
        snapshot = json.loads(await asyncio.wait_for(socket.recv(), 10))
        snapshot_ms = (time.perf_counter() - connected) * 1000
        assert snapshot["type"] == "replay_snapshot"
        await asyncio.to_thread(api_request, None, base_url, path + "/start", {})
        async with asyncio.timeout(120):
            while True:
                message = json.loads(await socket.recv())
                if message["type"] == "replay_day":
                    received = datetime.now(timezone.utc)
                    sequences.append(message["sequence"])
                    produced = datetime.fromisoformat(message["result"]["replay_time"])
                    push_latencies.append((received - produced).total_seconds() * 1000)
                session = message.get("session", {})
                if session.get("status") == "failed":
                    raise RuntimeError(session.get("error"))
                if session.get("status") == "completed":
                    break
    assert sequences == [1, 2], sequences
    saved = api_request(None, base_url, path + "/results?after=0&limit=100")
    assert [item["sequence"] for item in saved["results"]] == sequences
    return {"run_index": run_index, "session_id": session_id, "snapshot_ms": round(snapshot_ms, 3), "push_ms": push_latencies, "sequences": sequences, "result_catchup_verified": True}


async def execute(args):
    runs = [await run_once(args.base_url, args.start, args.end, index) for index in range(1, args.runs + 1)]
    pushes = [value for run in runs for value in run["push_ms"]]
    snapshots = [run["snapshot_ms"] for run in runs]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": git_revision(),
        "configuration": {"base_url": args.base_url, "start": args.start, "end": args.end, "runs": args.runs, "speed": 10, "mode": "local"},
        "runs": runs,
        "summary": {"snapshot_ms": {"p50": percentile(snapshots, 0.5), "p95": percentile(snapshots, 0.95)}, "push_ms": {"p50": percentile(pushes, 0.5), "p95": percentile(pushes, 0.95), "max": percentile(pushes, 1), "samples": len(pushes)}, "push_p95_within_100ms": percentile(pushes, 0.95) < 100, "note": "推送延迟使用结果内 UTC replay_time 到本客户端收到 WebSocket 消息的时间差，不是两条消息之间的间隔"},
    }


def main():
    parser = argparse.ArgumentParser(description="真实本地回放 WebSocket 快照与逐日推送延迟")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--start", default="2026-04-27")
    parser.add_argument("--end", default="2026-04-28")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("runs 必须为正数")
    report = asyncio.run(execute(args))
    output = args.output or Path(__file__).resolve().parents[1] / "data" / "benchmarks" / f"websocket-performance-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "output": str(output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
