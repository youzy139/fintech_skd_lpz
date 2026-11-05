"""Isolated real Redis/Uvicorn acceptance; never uses application identities or data.

Run with PYTHONPATH=.;server and an empty disposable Redis on localhost:16381.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import redis
from fastapi import FastAPI, WebSocket
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.leases import ConnectionLeases


def client(port):
    return redis.Redis(host="127.0.0.1", port=port, socket_timeout=0.3, socket_connect_timeout=0.3, retry=Retry(NoBackoff(), 0))


def serve(args):
    import uvicorn
    from app.core.governance import GovernanceMiddleware, SharedLimiter

    app = FastAPI()
    leases = ConnectionLeases(client(args.redis_port), args.namespace)
    app.add_middleware(GovernanceMiddleware, limiter=SharedLimiter(), service_name="acceptance", leases=leases)

    @app.get("/ready")
    def ready():
        return {"ok": True}

    @app.websocket("/ws/test")
    async def subscription(ws: WebSocket):
        await ws.accept()
        await ws.send_text("ready")
        await asyncio.Event().wait()

    uvicorn.run(app, host="127.0.0.1", port=args.serve, log_level="error")


async def verify(args):
    import websockets
    from websockets.exceptions import ConnectionClosed

    checks = []
    namespace = "marketlens:acceptance:" + uuid4().hex
    pools = [ConnectionLeases(client(args.redis_port), namespace, per_user=3, total=5) for _ in range(2)]
    held = []
    processes, sockets = [], []
    try:
        with ThreadPoolExecutor(8) as executor:
            attempts = list(executor.map(lambda i: pools[i % 2].acquire("alice"), range(20)))
        held = [item for item in attempts if item]
        assert len(held) == 3
        bob = pools[1].acquire("bob")
        charlie = pools[0].acquire("charlie")
        assert bob and charlie and pools[1].acquire("dave") is None
        for lease in held + [bob, charlie]:
            pools[0].release(lease)
        checks.append("real Redis atomic per-user and service-total limits across two pool instances")

        ports = []
        for _ in range(2):
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                ports.append(reservation.getsockname()[1])
            env = dict(os.environ)
            root = Path(__file__).resolve().parents[2]
            env["PYTHONPATH"] = os.pathsep.join([str(root), str(root / "server")])
            processes.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", str(ports[-1]), "--redis-port", str(args.redis_port), "--namespace", namespace], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        from urllib.request import build_opener, ProxyHandler
        opener = build_opener(ProxyHandler({}))
        for port in ports:
            for _ in range(100):
                try:
                    with opener.open(f"http://127.0.0.1:{port}/ready", timeout=0.3):
                        break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                raise TimeoutError("isolated Uvicorn readiness")

        async def connect(index):
            ws = await websockets.connect(f"ws://127.0.0.1:{ports[index]}/ws/test", proxy=None)
            sockets.append(ws)
            return ws

        async def accepted(index):
            ws = await connect(index)
            assert await asyncio.wait_for(ws.recv(), 3) == "ready"
            return ws

        async def rejected():
            ws = await connect(1)
            try:
                await asyncio.wait_for(ws.recv(), 3)
            except ConnectionClosed as error:
                assert error.rcvd.code == 4429 and error.rcvd.reason == "connection_limit"
            else:
                raise AssertionError("connection unexpectedly accepted")

        await accepted(0)
        second = await accepted(0)
        survivor = await accepted(1)
        await rejected()
        await second.close()
        # The remote middleware releases after its application exits.
        await asyncio.sleep(0.2)
        await accepted(0)
        checks.append("two actual Uvicorn processes share three slots; fourth rejected; disconnect releases a slot")
        processes[0].kill()
        processes[0].wait(timeout=5)
        await rejected()
        await asyncio.sleep(31)
        await accepted(1)
        await accepted(1)
        await rejected()
        assert survivor.close_code is None
        checks.append("crashed owner slots recovered after default 30-second TTL; idle survivor renewed across TTL")
        # Only the explicitly named disposable Redis is stopped, never formal Redis.
        if args.redis_container:
            if args.redis_container != "marketlens-connection-redis":
                raise ValueError("only the disposable marketlens-connection-redis container may be stopped")
            subprocess.run(["docker.exe", "stop", args.redis_container], capture_output=True, check=True, timeout=20)
            try:
                try:
                    await asyncio.wait_for(survivor.recv(), 12)
                except ConnectionClosed as error:
                    assert error.rcvd.code == 1013
                else:
                    raise AssertionError("idle socket survived failed renewal")
            finally:
                subprocess.run(["docker.exe", "start", args.redis_container], capture_output=True, check=True, timeout=20)
            await accepted(1)
            checks.append("Redis outage closes idle subscription 1013; new connection works after Redis recovery")
        return {"complete": True, "checks": checks, "lease_ttl_seconds": 30, "per_user": 3, "uses_real_market_data": False, "scope": "transport concurrency only; not a financial replay correctness benchmark"}
    finally:
        await asyncio.gather(*(ws.close() for ws in sockets), return_exceptions=True)
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        # Delete only this run's random namespace, never FLUSHDB.
        connection = client(args.redis_port)
        keys = list(connection.scan_iter(namespace + "*"))
        if keys:
            connection.delete(*keys)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-port", type=int, default=16381)
    parser.add_argument("--redis-container", default="")
    parser.add_argument("--serve", type=int, default=0)
    parser.add_argument("--namespace", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args)
    else:
        result = asyncio.run(verify(args))
        text = json.dumps(result, indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf8")
        print(text)
