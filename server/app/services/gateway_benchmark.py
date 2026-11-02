from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

import websockets
from websockets.exceptions import ConnectionClosed

from app.services.feature_proxy import websocket_url
from app.services.replay_benchmark import comparable_result, git_revision, results_close


def request(base, path, payload=None, key=None):
    headers = {"X-Request-ID": "gateway-eval-" + uuid4().hex, "Content-Type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    body = None if payload is None else json.dumps(payload).encode()
    upstream = Request(base + path, data=body, headers=headers)
    started = time.perf_counter()
    try:
        response = build_opener(ProxyHandler({})).open(upstream, timeout=60)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"non_json_response": True, "content_type": response.headers.get("Content-Type")}
        return {"status": response.code, "body": body, "request_id_preserved": response.headers.get("X-Request-ID") == headers["X-Request-ID"], "ms": round((time.perf_counter() - started) * 1000, 3)}


async def replay(base, start, end):
    payload = {"start_date": start, "end_date": end, "speed": 10, "mode": "local"}
    key = "gateway-eval-" + uuid4().hex
    created = await asyncio.to_thread(request, base, "/api/replay/sessions", payload, key)
    assert created["status"] == 201, created
    session = created["body"]["id"]
    duplicate = await asyncio.to_thread(request, base, "/api/replay/sessions", payload, key)
    assert duplicate["body"]["id"] == session
    path = f"/api/replay/sessions/{session}"
    sequences = []
    started = time.perf_counter()
    async with websockets.connect(websocket_url(base, f"/ws/replay/{session}", ""), proxy=None, open_timeout=10) as ws:
        snapshot = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert snapshot["type"] == "replay_snapshot"
        result = await asyncio.to_thread(request, base, path + "/start", {}, key + "-start")
        assert result["status"] == 200
        async with asyncio.timeout(120):
            while True:
                message = json.loads(await ws.recv())
                if message["type"] == "replay_day":
                    sequences.append(message["sequence"])
                state = message.get("session", {})
                if state.get("status") == "failed":
                    raise RuntimeError(state.get("error"))
                if state.get("status") == "completed":
                    break
    saved = await asyncio.to_thread(request, base, path + "/results?after=0&limit=100")
    items = saved["body"]["results"]
    assert sequences == list(range(1, len(items) + 1)) and items
    tail = await asyncio.to_thread(request, base, path + "/results?after=1&limit=100")
    assert tail["body"]["results"] == items[1:]
    async with websockets.connect(websocket_url(base, f"/ws/replay/{session}", ""), proxy=None) as ws:
        resumed = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert resumed["session"]["latest_sequence"] == len(items)
    return {"session_id": session, "sequences": sequences, "idempotent_create": True, "reconnect_and_catchup": True, "total_ms": round((time.perf_counter() - started) * 1000, 3), "results": [comparable_result(item["result"]) for item in items]}


async def missing_websocket(base):
    async with websockets.connect(websocket_url(base, "/ws/replay/gateway-eval-missing", ""), proxy=None, open_timeout=10) as ws:
        try:
            await asyncio.wait_for(ws.recv(), 10)
        except ConnectionClosed as error:
            code = error.rcvd.code if error.rcvd else None
            assert code == 4404, code
            return code
    raise AssertionError("Missing replay must close with 4404")


async def evaluate(args, report):
    routes = [("market", "/api/regimes/latest", None, 200), ("catalog", "/api/data/records?limit=1", None, 200), ("alerts", "/api/alerts?limit=1", None, 200), ("graphql", "/graphql", {"query": "{ assets latestState sourceSummary }"}, 200), ("validation", "/api/data/records?limit=0", None, 422), ("missing", "/api/replay/sessions/gateway-eval-missing", None, 404), ("openapi", "/openapi.json", None, 200)]
    for specification in args.entrance:
        name, base = specification.split("=", 1)
        record = report["entrances"][name] = {"base_url": base, "routes": {}}
        for label, path, payload, status in routes:
            samples = [await asyncio.to_thread(request, base, path, payload) for _ in range(args.samples)]
            assert all(item["status"] == status for item in samples), (name, label, samples)
            assert all(item["request_id_preserved"] for item in samples), (name, label, "request ID lost")
            if label == "graphql":
                assert "errors" not in samples[0]["body"]
            if label == "openapi":
                assert "openapi" in samples[0]["body"] and "/api/replay/sessions" in samples[0]["body"]["paths"]
            if status >= 400:
                assert samples[0]["body"]["error"]["request_id"]
            record["routes"][label] = {"status": status, "samples_ms": [item["ms"] for item in samples], "median_ms": statistics.median(item["ms"] for item in samples), "request_id_preserved": all(item["request_id_preserved"] for item in samples), "body": samples[0]["body"]}
        record["missing_ws_code"] = await missing_websocket(base)
        record["replay"] = await replay(base, args.start, args.end)
        print(name + ": contracts and replay passed", flush=True)
    records = list(report["entrances"].values())
    report["equal_success_bodies"] = all(records[0]["routes"][label]["body"] == record["routes"][label]["body"] for record in records[1:] for label in ("market", "catalog", "alerts", "graphql"))
    report["equal_replay_results"] = all(results_close(records[0]["replay"]["results"], record["replay"]["results"]) for record in records[1:])
    assert report["equal_success_bodies"] and report["equal_replay_results"]


def main():
    parser = argparse.ArgumentParser(description="Real gateway contract and small sequential latency comparison; creates persistent local replay sessions")
    parser.add_argument("--entrance", action="append", required=True, help="name=http://host:port")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--start", default="2026-04-27")
    parser.add_argument("--end", default="2026-04-28")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1 or any("=" not in item for item in args.entrance):
        parser.error("samples must be positive; entrances must be name=url")
    names = [item.split("=", 1)[0] for item in args.entrance]
    if len(set(names)) != len(names):
        parser.error("entrance names must be unique")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "git_revision": git_revision(), "samples": args.samples, "start": args.start, "end": args.end, "complete": False, "entrances": {}}
    try:
        asyncio.run(evaluate(args, report))
        report["complete"] = True
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
