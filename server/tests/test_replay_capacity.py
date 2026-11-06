from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError

from app.core.config import load_config
from app.core.leases import ConnectionLeases
from app.services.replay import ReplayManager
from app.services.replay_capacity import ReplayCapacityError, ReplayLeaseLost
from app.services.replay_store import ReplayStore
from server.tests.test_replay import MODEL_SETTINGS, sample_series
from server.tests.test_replay_persistence import app, configure


def manager(tmp_path, capacity=None, name="replay.db"):
    config = replace(load_config(), database_path=tmp_path / name, model=MODEL_SETTINGS, replay={"interval_ms": 10000})
    return ReplayManager(SimpleNamespace(series=sample_series()), config, capacity=capacity)


def create(owner):
    days = owner.catalog.dates[45:48]
    item = owner.create(days[0], days[-1], 1)
    return owner.get(item["id"])


def test_capacity_rejection_pause_release_resume_and_duplicate(tmp_path):
    async def run():
        owner = manager(tmp_path, ConnectionLeases(per_user=1, total=1))
        first, second = create(owner), create(owner)
        try:
            await first.start("start")
            assert (await first.start("start"))["status"] == "running"
            with pytest.raises(ReplayCapacityError) as error:
                await second.start()
            assert error.value.status_code == 429
            assert second.snapshot()["status"] == "pending"
            await first.pause()
            assert first.compute_lease is None
            assert first.pipeline is None
            await second.start()
            with pytest.raises(ReplayCapacityError):
                await first.resume()
            assert first.clock.status == "paused"
            await second.pause()
            await first.resume()
        finally:
            await owner.close()
        assert owner.capacity.local == {}
    asyncio.run(run())


def test_restart_rejected_without_deleting_saved_results(tmp_path):
    async def run():
        pool = ConnectionLeases(per_user=1, total=1)
        owner = manager(tmp_path, pool)
        first, second = create(owner), create(owner)
        try:
            await first.start()
            for _ in range(1000):
                if first.timed_days:
                    break
                await asyncio.sleep(0.01)
            await first.pause()
            before = owner.store.results(first.id)
            assert len(before["results"]) == 1
            await second.start()
            with pytest.raises(ReplayCapacityError):
                await first.restart()
            assert owner.store.results(first.id) == before
        finally:
            await owner.close()
    asyncio.run(run())


def test_shutdown_of_stale_replica_cannot_overwrite_owner(tmp_path):
    async def run():
        pool = ConnectionLeases(per_user=1, total=2)
        owner = manager(tmp_path, pool)
        session = create(owner)
        replica = manager(tmp_path, pool)
        try:
            await session.start()
            before = owner.store.load_session(session.id)
            await replica.close()
            assert owner.store.load_session(session.id) == before
        finally:
            await owner.close()
    asyncio.run(run())


def test_store_fences_stale_snapshot_result_reset_and_operation(tmp_path):
    owner = manager(tmp_path)
    session = create(owner)
    other = ReplayStore(owner.config.database_path)
    snapshot = session.snapshot()
    owner.store.claim(session.id, "old")
    other.claim(session.id, "new")
    try:
        for write in (
            lambda: owner.store.save_session(snapshot, "old"),
            lambda: owner.store.record_result(snapshot, 1, {"event_time": "2024-03-04"}, "old"),
            lambda: owner.store.reset_session(snapshot, "old"),
            lambda: owner.store.save_operation(session.id, "start", "key", {}, snapshot, "old"),
            lambda: owner.store.save_session(snapshot),
        ):
            with pytest.raises(ReplayLeaseLost):
                write()
        assert other.results(session.id)["results"] == []
        other.save_session(snapshot, "new")
    finally:
        other.close()
        owner.store.close()


def test_compute_cancellation_drains_thread_before_releasing_slot(tmp_path):
    async def run():
        owner = manager(tmp_path, ConnectionLeases(per_user=1, total=1))
        first, second = create(owner), create(owner)
        entered, exit_worker = threading.Event(), threading.Event()
        original = first._build_engine
        def slow_engine():
            entered.set()
            exit_worker.wait(5)
            return original()
        first._build_engine = slow_engine
        try:
            await first.start()
            assert await asyncio.to_thread(entered.wait, 5)
            stopping = asyncio.create_task(first.close())
            await asyncio.sleep(0.02)
            assert not stopping.done()
            with pytest.raises(ReplayCapacityError):
                await second.start()
            exit_worker.set()
            await stopping
            await second.start()
        finally:
            exit_worker.set()
            await owner.close()
    asyncio.run(run())


def test_redis_failure_is_503_and_does_not_start(tmp_path):
    class BrokenRedis:
        def eval(self, *args):
            raise ConnectionError("unavailable")
    async def run():
        owner = manager(tmp_path, ConnectionLeases(BrokenRedis(), per_user=1, total=1))
        session = create(owner)
        try:
            with pytest.raises(ReplayCapacityError) as error:
                await session.start()
            assert error.value.status_code == 503
            assert session.clock.status == "pending"
            assert session.task is None
        finally:
            await owner.close()
    asyncio.run(run())


def test_immediate_shutdown_before_task_starts_releases_slot(tmp_path):
    async def run():
        owner = manager(tmp_path, ConnectionLeases(per_user=1, total=1))
        session = create(owner)
        await session.start()
        await session.close()
        assert owner.capacity.local == {}
        assert owner.store.load_session(session.id)["stored_status"] == "paused"
        await owner.close()
    asyncio.run(run())


def test_pipeline_cleanup_keeps_slot_and_shutdown_waits(tmp_path, monkeypatch):
    from app.services.replay import LocalReplayPipeline
    async def run():
        entered, allow_close = asyncio.Event(), asyncio.Event()
        async def slow_close(self):
            entered.set()
            await allow_close.wait()
        monkeypatch.setattr(LocalReplayPipeline, "close", slow_close)
        owner = manager(tmp_path, ConnectionLeases(per_user=1, total=1))
        day = owner.catalog.dates[45]
        session = owner.get(owner.create(day, day, 1)["id"])
        second = create(owner)
        try:
            await session.start()
            await asyncio.wait_for(entered.wait(), 10)
            closing = asyncio.create_task(session.close())
            await asyncio.sleep(0.01)
            assert not closing.done()
            with pytest.raises(ReplayCapacityError):
                await second.start()
            allow_close.set()
            await closing
            await second.start()
        finally:
            allow_close.set()
            await owner.close()
    asyncio.run(run())


def test_capacity_http_contract(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path / "http.db")
    monkeypatch.setenv("REPLAY_MAX_RUNNING", "1")
    with app(sample_series(), tmp_path / "http.db") as http:
        days = sample_series()[0].frame["date"]
        payload = {"start_date": days.iloc[45].date().isoformat(), "end_date": days.iloc[65].date().isoformat(), "speed": 0.5}
        first = http.post("/api/replay/sessions", json=payload).json()["id"]
        second = http.post("/api/replay/sessions", json=payload).json()["id"]
        assert http.post(f"/api/replay/sessions/{first}/start").status_code == 200
        response = http.post(f"/api/replay/sessions/{second}/start")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert response.json()["error"]["code"] == "replay_capacity_exceeded"
        assert response.json()["error"]["request_id"]
        assert http.get(f"/api/replay/sessions/{second}").json()["status"] == "pending"
