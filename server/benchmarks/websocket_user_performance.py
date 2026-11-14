"""Measure replay WebSocket delivery with independent synthetic users on localhost."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import websockets
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.core.observability import percentile
from app.services.feature_proxy import websocket_url
from app.services.replay_benchmark import git_revision
from server.benchmarks.e2e_server import prepare
from server.benchmarks.independent_user_performance import read_json, wait_ready


def post_json(base_url: str, path: str, payload: dict, token: str, timeout: float = 60) -> dict:
    request = Request(base_url + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def metrics(values: list[float]) -> dict:
    return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95), "p99": percentile(values, 0.99), "max": percentile(values, 1), "samples": len(values)}


async def measure(base_url: str, tokens: list[str], admin_token: str, control_tokens: list[str], start: str, end: str, timeout: float) -> dict:
    created = await asyncio.to_thread(post_json, base_url, "/api/replay/sessions", {"start_date": start, "end_date": end, "speed": 10, "mode": "local"}, admin_token)
    session_id = created["id"]
    url = websocket_url(base_url, f"/ws/replay/{session_id}", "")
    sockets = []
    rejected = []
    snapshot_latencies = []

    async def connect(index: int):
        started = time.perf_counter()
        try:
            socket = await websockets.connect(url, additional_headers={"Authorization": "Bearer " + tokens[index]}, proxy=None, open_timeout=timeout, close_timeout=timeout)
            snapshot = json.loads(await asyncio.wait_for(socket.recv(), timeout))
            assert snapshot["type"] == "replay_snapshot"
            return index, socket, (time.perf_counter() - started) * 1000, None
        except ConnectionClosed as error:
            code = error.rcvd.code if error.rcvd else None
            return index, None, None, code

    connections = await asyncio.gather(*(connect(index) for index in range(len(tokens))))
    for index, socket, latency, rejection in connections:
        if socket is not None:
            sockets.append((index, socket))
            snapshot_latencies.append(latency)
        else:
            rejected.append({"user": index, "close_code": rejection})
    push_latencies = []
    catchup = {"attempted": False, "verified": False}
    try:
        if not rejected:
            async def collect(index: int, socket):
                sequences = []
                latencies = []
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 120))
                    if message["type"] == "replay_day":
                        sequences.append(message["sequence"])
                        if index == 0 and message["sequence"] == 1:
                            await socket.close()
                            return index, sequences, latencies
                        produced = datetime.fromisoformat(message["result"]["replay_time"])
                        latencies.append((datetime.now(timezone.utc) - produced).total_seconds() * 1000)
                    session = message.get("session", {})
                    if session.get("status") == "failed":
                        raise RuntimeError(session.get("error"))
                    if session.get("status") == "completed":
                        return index, sequences, latencies

            await asyncio.to_thread(post_json, base_url, f"/api/replay/sessions/{session_id}/start", {}, admin_token)
            completed = await asyncio.gather(*(collect(index, socket) for index, socket in sockets))
            for _, sequences, latencies in completed:
                push_latencies.extend(latencies)
            disconnected = next(item for item in completed if item[0] == 0)
            assert disconnected[1] == [1]
            assert all(sequences == [1, 2] for index, sequences, _ in completed if index != 0)
            saved = await asyncio.to_thread(read_json, base_url, f"/api/replay/sessions/{session_id}/results?after=1&limit=100", tokens[0], 30)
            catchup["attempted"] = True
            catchup["verified"] = [item["sequence"] for item in saved["results"]] == [2]
            async with websockets.connect(url, additional_headers={"Authorization": "Bearer " + tokens[0]}, proxy=None, open_timeout=timeout) as reconnected:
                snapshot = json.loads(await asyncio.wait_for(reconnected.recv(), timeout))
                catchup["snapshot_after_reconnect"] = snapshot["session"]["latest_sequence"]
                catchup["verified"] = catchup["verified"] and snapshot["session"]["latest_sequence"] == 2 and snapshot["session"]["status"] == "completed"
    finally:
        await asyncio.gather(*(socket.close() for _, socket in sockets), return_exceptions=True)
    slow_consumer = {"attempted": False, "verified": False}
    if not rejected:
        slow_created = await asyncio.to_thread(post_json, base_url, "/api/replay/sessions", {"start_date": start, "end_date": end, "speed": 10, "mode": "local"}, admin_token)
        slow_session_id = slow_created["id"]
        slow_url = websocket_url(base_url, f"/ws/replay/{slow_session_id}", "")
        slow_socket = await websockets.connect(slow_url, additional_headers={"Authorization": "Bearer " + tokens[0]}, proxy=None, open_timeout=timeout)
        try:
            await asyncio.to_thread(post_json, base_url, f"/api/replay/sessions/{slow_session_id}/start", {}, admin_token)
            for index in range(110):
                await asyncio.to_thread(post_json, base_url, f"/api/replay/sessions/{slow_session_id}/speed", {"speed": 1 if index % 2 == 0 else 2}, control_tokens[index % len(control_tokens)])
            queued = []
            async with asyncio.timeout(30):
                for _ in range(100):
                    queued.append(json.loads(await slow_socket.recv()))
            saved = await asyncio.to_thread(read_json, base_url, f"/api/replay/sessions/{slow_session_id}/results?after=0&limit=100", tokens[0], 30)
            slow_consumer = {
                "attempted": True,
                "generated_status_updates": 110,
                "queued_messages": len(queued),
                "initial_snapshot_outside_queue": queued[0]["type"] == "replay_snapshot",
                "latest_speed": queued[-1]["session"]["speed"],
                "rest_sequences": [item["sequence"] for item in saved["results"]],
            }
            slow_consumer["verified"] = len(queued) == 100 and slow_consumer["initial_snapshot_outside_queue"] and slow_consumer["latest_speed"] == 2 and slow_consumer["rest_sequences"] == [1, 2]
        finally:
            await slow_socket.close()
    return {
        "session_id": session_id,
        "accepted_connections": len(sockets),
        "rejected_connections": rejected,
        "snapshot_ms": metrics(snapshot_latencies),
        "push_ms": metrics(push_latencies),
        "catchup": catchup,
        "slow_consumer": slow_consumer,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="101 独立用户回放 WebSocket 推送与断线补拉；仅限本机合成环境")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--users", type=int, default=101)
    parser.add_argument("--max-connections", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--ready-timeout", type=float, default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("WebSocket 基准只能以本机为目标")
    if min(args.users, args.max_connections) < 1 or min(args.timeout, args.ready_timeout) <= 0 or not 1 <= args.port <= 65535:
        parser.error("users、max-connections、timeout 或端口参数无效")
    with socket.socket() as reservation:
        if reservation.connect_ex((args.host, args.port)) == 0:
            parser.error(f"固定基准端口 {args.port} 已被占用；请先停止所属预览，不自动更换端口")
    base_url = f"http://{args.host}:{args.port}"
    with tempfile.TemporaryDirectory(prefix="marketlens-websocket-performance-") as directory:
        prepare(Path(directory))
        from app.core.auth import auth_store

        store = auth_store()
        password = "synthetic-websocket-password-123"
        tokens = []
        for index in range(args.users):
            username = f"websocket-user-{index:03d}"
            store.save_user("benchmark", username, password, "observer", ["market", "catalog"], True, create=True)
            tokens.append(store.login(username, password))
        store.save_user("benchmark", "websocket-admin", password, "admin", ["market", "catalog"], True, create=True)
        admin_token = store.login("websocket-admin", password)
        control_tokens = []
        for index in range(8):
            username = f"websocket-operator-{index:02d}"
            store.save_user("benchmark", username, password, "analyst", ["market", "catalog"], True, create=True)
            control_tokens.append(store.login(username, password))
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "server")])
        environment["WS_MAX_CONNECTIONS_TOTAL"] = str(args.max_connections)
        process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "server"),
            "--host", args.host, "--port", str(args.port), "--log-level", "warning",
        ], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_ready(process, base_url, args.ready_timeout)
            assets = read_json(base_url, "/api/assets", admin_token, args.timeout)
            series = read_json(base_url, f"/api/assets/{assets[0]['code']}/series?limit=2", admin_token, args.timeout)
            start, end = [point["date"] for point in series["points"]]
            result = asyncio.run(measure(base_url, tokens, admin_token, control_tokens, start, end, args.timeout))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    rejected = len(result["rejected_connections"])
    push_p95 = result["push_ms"]["p95"]
    passed = args.users > 100 and rejected == 0 and push_p95 is not None and push_p95 < 100 and result["catchup"]["verified"] and result["slow_consumer"]["verified"]
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "base_url": base_url, "users": args.users, "max_connections": args.max_connections,
            "speed": 10, "mode": "local", "think_time_seconds": 0,
            "note": "同一回放会话的独立用户订阅；不是 101 个同时运行的回放",
        },
        "identity": {"type": "independent_synthetic_user_jwt", "users": args.users, "unique_sessions": len(set(tokens))},
        "environment": {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(), "git_revision": os.getenv("MARKETLENS_GIT_REVISION") or git_revision()},
        "measurement": result,
        "target_evaluation": {
            "independent_users_above_100": args.users > 100,
            "all_connections_accepted": rejected == 0,
            "push_p95_below_100ms": push_p95 is not None and push_p95 < 100,
            "disconnect_catchup_verified": result["catchup"]["verified"],
            "slow_consumer_catchup_verified": result["slow_consumer"]["verified"],
            "passes_provisional_target": passed,
            "note": "推送延迟为结果 UTC replay_time 到本客户端接收的时间差；连接被拒绝时没有推送样本，不能当作延迟通过",
        },
    }
    output = args.output or ROOT / "server" / "data" / "benchmarks" / f"websocket-users-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "accepted": result["accepted_connections"], "rejected": result["rejected_connections"], "push_ms": result["push_ms"], "snapshot_ms": result["snapshot_ms"], "catchup": result["catchup"], "slow_consumer": result["slow_consumer"], "passes_provisional_target": passed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
