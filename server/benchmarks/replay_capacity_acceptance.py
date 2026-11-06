"""Two real replay processes, disposable Redis, original read-only market data.

Run with PYTHONPATH=.;server; Redis must be disposable (default port 16381).
No application accounts, formal replay databases or original inputs are written.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

import redis
from fastapi import FastAPI
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import load_config
from app.core.leases import ConnectionLeases
from app.services.replay import ReplayManager
from app.services.replay_benchmark import comparable_result, results_close
from app.services.replay_capacity import ReplayCapacityError
from market_core.ingestion.assets import AssetRepository
from market_core.models.replay import HistoricalMarketReplay


def client(port):
    return redis.Redis(host="127.0.0.1", port=port, socket_timeout=0.3, socket_connect_timeout=0.3, retry=Retry(NoBackoff(), 0))


def serve(args):
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi.responses import JSONResponse

    config = replace(load_config(), database_path=Path(args.database), replay={"interval_ms": 100000})
    series, _ = AssetRepository(config.data_root).load_all()
    pool = ConnectionLeases(client(args.redis_port), args.namespace, per_user=1, total=1, ttl=3)
    owner = ReplayManager(SimpleNamespace(series=series), config, capacity=pool)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await owner.close()

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(ReplayCapacityError)
    async def rejected(request, error):
        return JSONResponse({"code": error.code}, error.status_code)

    @app.get("/ready")
    def ready():
        return {"assets": len(series)}

    @app.post("/create")
    def create():
        return owner.create(date(2026, 4, 27), date(2026, 4, 28), 10)

    @app.post("/{sid}/{action}")
    async def control(sid: str, action: str):
        return await getattr(owner.get(sid), action)()

    @app.get("/{sid}")
    def status(sid: str):
        return owner.get(sid).snapshot()

    @app.get("/{sid}/results")
    def results(sid: str):
        return owner.results(sid, 0, 100)

    uvicorn.run(app, host="127.0.0.1", port=args.serve, log_level="error")


def verify(args):
    checks, processes, ports = [], [], []
    namespace = "marketlens:capacity:acceptance:{" + uuid4().hex + "}"
    connection = client(args.redis_port)
    connection.ping()
    opener = build_opener(ProxyHandler({}))

    def request(index, path, post=False, expected=200):
        try:
            response = opener.open(Request(f"http://127.0.0.1:{ports[index]}" + path, data=b"{}" if post else None), timeout=120)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == expected, (path, response.status)
            return json.load(response)

    def wait(index, sid, predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = request(index, "/" + sid)
            assert snapshot["status"] != "failed", snapshot["error"]
            if predicate(snapshot):
                return snapshot
            time.sleep(0.05)
        raise TimeoutError("replay acceptance")

    with tempfile.TemporaryDirectory(prefix="marketlens-capacity-") as directory:
        try:
            for index in range(2):
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    ports.append(reservation.getsockname()[1])
                processes.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", str(ports[-1]), "--redis-port", str(args.redis_port), "--namespace", namespace, "--database", str(Path(directory) / f"replay-{index}.db")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ)))
                for _ in range(200):
                    try:
                        assert request(index, "/ready")["assets"] == 39
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise TimeoutError("replay process startup")
            first = request(0, "/create", True)["id"]
            second = request(1, "/create", True)["id"]
            request(0, f"/{first}/start", True)
            assert request(1, f"/{second}/start", True, 429)["code"] == "replay_capacity_exceeded"
            wait(0, first, lambda s: s["processed_days"] == 1)
            request(0, f"/{first}/pause", True)
            request(1, f"/{second}/start", True)
            assert request(0, f"/{first}/resume", True, 429)["code"] == "replay_capacity_exceeded"
            wait(1, second, lambda s: s["processed_days"] == 1)
            time.sleep(3.3)
            request(0, f"/{first}/resume", True, 429)
            checks.append("two actual replay processes share one Redis slot; idle pacing renews beyond TTL; pause releases after cleanup")
            processes[1].kill()
            processes[1].wait(timeout=10)
            time.sleep(3.2)
            request(0, f"/{first}/resume", True)
            wait(0, first, lambda s: s["status"] == "completed")
            actual = request(0, f"/{first}/results")["results"]
            config = load_config()
            series, _ = AssetRepository(config.data_root).load_all()
            from app.services.replay import ReplayDataCatalog
            catalog = ReplayDataCatalog(series)
            days = catalog.dates_between(date(2026, 4, 27), date(2026, 4, 28))
            engine = HistoricalMarketReplay(series, config.model, config.alerts, days[0])
            expected = json.loads(json.dumps([comparable_result(asdict(engine.advance(catalog.read(day)))) for day in days]))
            assert [item["sequence"] for item in actual] == [1, 2]
            assert results_close([comparable_result(item["result"]) for item in actual], expected)
            checks.append("killed owner slot expires; paused real 39-asset replay resumes with sequences 1,2 and matches deterministic baseline")
            # Delete only this disposable run's lease keys to simulate Redis loss.
            third = request(0, "/create", True)["id"]
            request(0, f"/{third}/start", True)
            wait(0, third, lambda s: s["processed_days"] == 1)
            keys = list(connection.scan_iter(namespace + "*"))
            connection.delete(*keys)
            stopped = wait(0, third, lambda s: s["status"] == "paused")
            assert stopped["processed_days"] == 1
            checks.append("lost Redis lease pauses at committed day without fabricating results")
            return {"complete": True, "checks": checks, "assets": 39, "sequences": [1, 2], "baseline_equal": True, "ttl_seconds": 3, "scope": "local pipeline, two independent replay databases; not Flink crash reconciliation or active-active service failover"}
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
            keys = list(connection.scan_iter(namespace + "*"))
            if keys:
                connection.delete(*keys)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-port", type=int, default=16381)
    parser.add_argument("--namespace", default="")
    parser.add_argument("--serve", type=int, default=0)
    parser.add_argument("--database", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args)
    else:
        result = verify(args)
        if args.output:
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        print(json.dumps(result, ensure_ascii=False))
