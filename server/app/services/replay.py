from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import date
from time import monotonic
from typing import Any
from uuid import uuid4

import pandas as pd

from app.core.config import AppConfig
from app.core.observability import log_event
from app.services.flink import FlinkReplayPipeline
from app.services.kafka import KafkaReplayPipeline
from app.services.replay_store import ReplayStore
from market_core.domain.replay import AssetObservation, ReplayClock, ReplayDayInput, ReplayDayResult
from market_core.models.replay import HistoricalMarketReplay

replay_logger = logging.getLogger("marketlens.replay")


class LocalReplayPipeline:
    def __init__(self, dates: tuple[date, ...], catalog):
        self.dates = dates
        self.catalog = catalog
        self.stats = {"produced_events": 0, "consumed_events": 0, "duplicate_events": 0, "retry_count": 0, "commit_count": 0}

    async def start(self) -> None:
        self.stats["produced_events"] = len(self.dates)

    async def next(self, expected_date: date) -> ReplayDayInput:
        self.stats["consumed_events"] += 1
        return self.catalog.read(expected_date)

    async def ack(self, batch: ReplayDayInput) -> None:
        self.stats["commit_count"] += 1

    async def close(self) -> None:
        pass


class ReplayDataCatalog:
    def __init__(self, series):
        self.series = series
        self.dates = tuple(sorted({day.date() for item in series for day in item.frame["date"]}))

    def calendar(self) -> dict[str, Any]:
        if not self.dates:
            raise RuntimeError("没有可用于历史回放的行情日期")
        suggested = self.dates[-min(20, len(self.dates))]
        return {"min_date": self.dates[0].isoformat(), "max_date": self.dates[-1].isoformat(), "suggested_start": suggested.isoformat(), "suggested_end": self.dates[-1].isoformat()}

    def dates_between(self, start: date, end: date) -> tuple[date, ...]:
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        dates = tuple(day for day in self.dates if start <= day <= end)
        if not dates:
            raise ValueError("所选范围内没有资产交易日")
        return dates

    def read(self, event_date: date) -> ReplayDayInput:
        day = pd.Timestamp(event_date)
        observations = []
        for item in self.series:
            rows = item.frame.loc[item.frame["date"] == day]
            for value in rows["value"]:
                observations.append(AssetObservation(item.meta.code, event_date, float(value)))
        return ReplayDayInput(event_date, tuple(observations))


class ReplaySession:
    def __init__(self, session_id: str, dates: tuple[date, ...], speed: float, catalog: ReplayDataCatalog, config: AppConfig, store: ReplayStore, mode: str = "local"):
        self.id = session_id
        self.mode = mode
        self.clock = ReplayClock(dates, speed)
        self.catalog = catalog
        self.config = config
        self.store = store
        self.engine: HistoricalMarketReplay | None = None
        self.pipeline = None
        self.run_id: str | None = None
        self.flink_job_id: str | None = None
        self.savepoint_path: str | None = None
        self.event_stats = {"produced_events": 0, "consumed_events": 0, "duplicate_events": 0, "retry_count": 0, "commit_count": 0}
        self.latest_result: ReplayDayResult | None = None
        self.latest_sequence = 0
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.restart_lock = asyncio.Lock()
        self.resumed = asyncio.Event()
        self.subscribers: set[asyncio.Queue] = set()
        self.pipeline_timing: dict[str, float] = {}
        self.engine_start_ms: float | None = None
        self.pipeline_start_ms: float | None = None
        self.last_day_timing: dict[str, Any] | None = None
        self.timed_days = 0
        self.total_day_ms = 0.0
        self.max_day_ms = 0.0
        self.recovery_state = "none"
        self.recovery_count = 0
        self.recovery_pending = False
        self.rebuild_ms: float | None = None

    def snapshot(self) -> dict[str, Any]:
        total = len(self.clock.dates)
        if self.pipeline:
            self.event_stats = dict(self.pipeline.stats)
            self.pipeline_timing = dict(getattr(self.pipeline, "timing", {}))
            self.flink_job_id = getattr(self.pipeline, "flink_job_id", None)
            self.savepoint_path = getattr(self.pipeline, "savepoint_path", None) or self.savepoint_path
        last_day = None
        if self.last_day_timing:
            last_day = {key: round(value, 3) if isinstance(value, float) else value for key, value in self.last_day_timing.items()}
        current_date = self.clock.dates[self.timed_days - 1].isoformat() if self.timed_days else None
        return {
            "id": self.id,
            "run_id": self.run_id,
            "flink_job_id": self.flink_job_id,
            "savepoint_path": self.savepoint_path,
            "mode": self.mode,
            "start_date": self.clock.dates[0].isoformat(),
            "end_date": self.clock.dates[-1].isoformat(),
            "status": self.clock.status,
            "speed": self.clock.speed,
            "processed_days": self.timed_days,
            "total_days": total,
            "current_date": current_date,
            "progress": self.timed_days / total,
            "error": self.clock.error,
            "latest_sequence": self.latest_sequence,
            "recovery": {
                "state": self.recovery_state,
                "count": self.recovery_count,
                "rebuild_ms": round(self.rebuild_ms, 3) if self.rebuild_ms is not None else None,
            },
            "event_stats": dict(self.event_stats),
            "timing": {
                "engine_start_ms": round(self.engine_start_ms, 3) if self.engine_start_ms is not None else None,
                "pipeline_start_ms": round(self.pipeline_start_ms, 3) if self.pipeline_start_ms is not None else None,
                "last_day": last_day,
                "processed_days": self.timed_days,
                "total_day_ms": round(self.total_day_ms, 3),
                "average_day_ms": round(self.total_day_ms / self.timed_days, 3) if self.timed_days else None,
                "max_day_ms": round(self.max_day_ms, 3),
                "pipeline": {key: round(value, 3) for key, value in self.pipeline_timing.items()},
            },
            "latest_result": asdict(self.latest_result) if self.latest_result else None,
        }

    def persist(self) -> None:
        self.store.save_session(self.snapshot())

    def operation(self, action: str, key: str | None, request: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.store.operation(self.id, action, key, request or {})

    def save_operation(self, action: str, key: str | None, request: dict[str, Any] | None = None) -> None:
        self.store.save_operation(self.id, action, key, request or {}, self.snapshot())

    def restore(self, stored: dict[str, Any]) -> None:
        self.run_id = stored.get("run_id")
        self.flink_job_id = stored.get("flink_job_id")
        self.savepoint_path = stored.get("savepoint_path")
        self.event_stats = stored.get("event_stats", self.event_stats)
        timing = stored.get("timing", {})
        self.pipeline_timing = timing.get("pipeline", {})
        self.engine_start_ms = timing.get("engine_start_ms")
        self.pipeline_start_ms = timing.get("pipeline_start_ms")
        self.last_day_timing = timing.get("last_day")
        self.total_day_ms = timing.get("total_day_ms", 0.0)
        self.max_day_ms = timing.get("max_day_ms", 0.0)
        self.latest_sequence = stored.get("latest_sequence", 0)
        recovery = stored.get("recovery", {})
        self.recovery_count = recovery.get("count", 0)
        self.rebuild_ms = recovery.get("rebuild_ms")
        self.clock.position = stored["stored_position"]
        self.clock.status = stored["stored_status"]
        self.clock.error = stored.get("error")
        self.timed_days = self.clock.position
        if self.clock.status in {"running", "paused"}:
            self.clock.status = "paused"
            self.recovery_pending = True
            self.recovery_state = "paused"
        else:
            self.recovery_state = recovery.get("state", "none")

    async def publish(self, message: dict[str, Any]) -> None:
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)

    async def status_message(self, message_type: str = "replay_status") -> None:
        self.persist()
        await self.publish({"type": message_type, "session": self.snapshot()})

    async def start(self, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.lock:
            cached = self.operation("start", idempotency_key)
            if cached:
                return cached
            if self.clock.status == "running" and self.task and not self.task.done():
                return self.snapshot()
            self.clock.start()
            self.resumed.set()
            await self.status_message()
            self.task = asyncio.create_task(self._run())
            snapshot = self.snapshot()
            self.save_operation("start", idempotency_key)
            return snapshot

    async def pause(self, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.lock:
            cached = self.operation("pause", idempotency_key)
            if cached:
                return cached
            if self.clock.status != "paused":
                self.clock.pause()
            self.resumed.clear()
            await self.status_message()
            self.save_operation("pause", idempotency_key)
            return self.snapshot()

    async def resume(self, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.lock:
            cached = self.operation("resume", idempotency_key)
            if cached:
                return cached
            if self.clock.status == "running" and self.task and not self.task.done():
                return self.snapshot()
            self.clock.resume()
            if self.recovery_pending:
                self.recovery_state = "rebuilding"
                self.recovery_count += 1
            self.resumed.set()
            await self.status_message()
            if not self.task or self.task.done():
                self.task = asyncio.create_task(self._run())
            snapshot = self.snapshot()
            self.save_operation("resume", idempotency_key)
            return snapshot

    async def set_speed(self, speed: float, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.lock:
            request = {"speed": speed}
            cached = self.operation("speed", idempotency_key, request)
            if cached:
                return cached
            self.clock.set_speed(speed)
            await self.status_message()
            self.save_operation("speed", idempotency_key, request)
            return self.snapshot()

    async def restart(self, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.restart_lock:
            cached = self.operation("restart", idempotency_key)
            if cached:
                return cached
            task = self.task
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            async with self.lock:
                self.clock.restart()
                self.engine = None
                self.pipeline = None
                self.task = None
                self.run_id = None
                self.flink_job_id = None
                self.savepoint_path = None
                self.event_stats = {key: 0 for key in self.event_stats}
                self.latest_result = None
                self.latest_sequence = 0
                self.pipeline_timing = {}
                self.engine_start_ms = None
                self.pipeline_start_ms = None
                self.last_day_timing = None
                self.timed_days = 0
                self.total_day_ms = 0.0
                self.max_day_ms = 0.0
                self.recovery_state = "none"
                self.recovery_pending = False
                self.rebuild_ms = None
                snapshot = self.snapshot()
                self.store.reset_session(snapshot)
                await self.publish({"type": "replay_reset", "session": snapshot})
            snapshot = await self.start()
            self.save_operation("restart", idempotency_key)
            return snapshot

    def _build_engine(self) -> HistoricalMarketReplay:
        engine = HistoricalMarketReplay(self.catalog.series, self.config.model, self.config.alerts, self.clock.dates[0])
        for event_date in self.clock.dates[:self.clock.position]:
            engine.advance(self.catalog.read(event_date))
        return engine

    async def _run(self) -> None:
        pipeline = None
        try:
            remaining_dates = self.clock.dates[self.clock.position:]
            if self.mode == "flink":
                settings = {**self.config.kafka, "topic": self.config.flink["output_topic"], "produce_topic": self.config.kafka["topic"], "read_committed": True, "emit_end_of_input": True}
                pipeline = FlinkReplayPipeline(self.id, remaining_dates, self.catalog, settings, self.config.flink)
            elif self.mode == "kafka":
                pipeline = KafkaReplayPipeline(self.id, remaining_dates, self.catalog, self.config.kafka)
            else:
                pipeline = LocalReplayPipeline(remaining_dates, self.catalog)
            if self.run_id and hasattr(pipeline, "run_id"):
                pipeline.run_id = self.run_id
            self.pipeline = pipeline
            self.run_id = getattr(pipeline, "run_id", None) or self.run_id or uuid4().hex
            async with self.lock:
                if self.engine is None:
                    engine_started = monotonic()
                    self.engine = await asyncio.to_thread(self._build_engine)
                    self.engine_start_ms = (monotonic() - engine_started) * 1000
                    if self.clock.position and self.recovery_pending:
                        self.rebuild_ms = self.engine_start_ms
                    self.recovery_pending = False
                    if self.recovery_state == "rebuilding":
                        self.recovery_state = "completed"
                pipeline_started = monotonic()
                await pipeline.start()
                self.pipeline_start_ms = (monotonic() - pipeline_started) * 1000
                self.pipeline_timing = dict(getattr(pipeline, "timing", {}))
                await self.status_message()
            while self.clock.status in {"running", "paused"}:
                if self.clock.status == "paused":
                    await self.resumed.wait()
                    continue
                async with self.lock:
                    if self.clock.status == "paused":
                        continue
                    event_date = self.clock.advance()
                    day_started = monotonic()
                    batch = await pipeline.next(event_date)
                    input_finished = monotonic()
                    self.latest_result = await asyncio.to_thread(self.engine.advance, batch)
                    model_finished = monotonic()
                    await pipeline.ack(batch)
                    day_finished = monotonic()
                    self.last_day_timing = {
                        "event_date": event_date.isoformat(),
                        "input_ms": (input_finished - day_started) * 1000,
                        "model_ms": (model_finished - input_finished) * 1000,
                        "ack_ms": (day_finished - model_finished) * 1000,
                        "total_ms": (day_finished - day_started) * 1000,
                    }
                    self.timed_days += 1
                    self.latest_sequence = self.timed_days
                    self.total_day_ms += self.last_day_timing["total_ms"]
                    self.max_day_ms = max(self.max_day_ms, self.last_day_timing["total_ms"])
                    self.pipeline_timing = dict(getattr(pipeline, "timing", {}))
                    if self.clock.position == len(self.clock.dates):
                        self.clock.complete()
                    result = asdict(self.latest_result)
                    self.store.record_result(self.snapshot(), self.latest_sequence, result)
                    await self.publish({"type": "replay_day", "sequence": self.latest_sequence, "session": self.snapshot(), "result": result})
                    log_event(
                        replay_logger,
                        "replay_day_completed",
                        session_id=self.id,
                        run_id=self.run_id,
                        mode=self.mode,
                        event_time=event_date.isoformat(),
                        input_records=self.latest_result.input_records,
                        model_version=self.latest_result.model_version,
                        **{key: round(value, 3) for key, value in self.last_day_timing.items() if isinstance(value, float)},
                    )
                if self.clock.status == "running":
                    await asyncio.sleep(self.config.replay["interval_ms"] / 1000 / self.clock.speed)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with self.lock:
                if self.recovery_state == "rebuilding":
                    self.recovery_state = "failed"
                if self.clock.status not in {"completed", "failed"}:
                    self.clock.fail(str(error))
                await self.status_message("replay_error")
        finally:
            if pipeline:
                self.event_stats = dict(pipeline.stats)
                try:
                    await pipeline.close()
                except Exception as error:
                    async with self.lock:
                        self.clock.status = "failed"
                        self.clock.error = f"回放通道关闭失败：{error}"
                        await self.status_message("replay_error")
                finally:
                    self.pipeline_timing = dict(getattr(pipeline, "timing", {}))
                    self.flink_job_id = getattr(pipeline, "flink_job_id", None)
                    self.savepoint_path = getattr(pipeline, "savepoint_path", None) or self.savepoint_path
                await self.status_message()
            self.pipeline = None

    async def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.task = None
        self.clock.position = self.timed_days
        if self.clock.status == "running":
            self.clock.pause()
        if self.clock.status == "paused":
            self.recovery_pending = True
            self.recovery_state = "paused"
        self.persist()
        self.subscribers.clear()


class ReplayManager:
    def __init__(self, service, config: AppConfig, store: ReplayStore | None = None):
        self.catalog = ReplayDataCatalog(service.series)
        self.config = config
        self.store = store or ReplayStore(config.database_path)
        self.sessions: dict[str, ReplaySession] = {}
        for stored in self.store.load_sessions():
            dates = self.catalog.dates_between(date.fromisoformat(stored["start_date"]), date.fromisoformat(stored["end_date"]))
            session = ReplaySession(stored["id"], dates, stored["speed"], self.catalog, self.config, self.store, stored["mode"])
            session.restore(stored)
            latest = self.store.latest_result(session.id)
            if latest:
                sequence, result = latest
                result["observed_assets"] = tuple(result["observed_assets"])
                result["alerts"] = tuple(result["alerts"])
                session.latest_result = ReplayDayResult(**result)
                session.latest_sequence = max(session.latest_sequence, sequence)
            self.sessions[session.id] = session
        stored_current = self.store.current_id()
        self.current_id = stored_current if stored_current in self.sessions else (next(reversed(self.sessions)) if self.sessions else None)

    def calendar(self) -> dict[str, Any]:
        return self.catalog.calendar()

    def kafka_status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.kafka.get("enabled", False),
            "bootstrap_servers": self.config.kafka["bootstrap_servers"],
            "topic": self.config.kafka["topic"],
            "topic_partitions": self.config.kafka["topic_partitions"],
            "connection": "on-demand",
        }

    def flink_status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.flink.get("enabled", False),
            "rest_url": self.config.flink["rest_url"],
            "output_topic": self.config.flink["output_topic"],
            "late_topic": self.config.flink["late_topic"],
            "checkpoint_interval_ms": self.config.flink["checkpoint_interval_ms"],
            "connection": "on-demand",
        }

    def create(self, start: date, end: date, speed: float, mode: str = "local", idempotency_key: str | None = None) -> dict[str, Any]:
        request = {"start_date": start.isoformat(), "end_date": end.isoformat(), "speed": speed, "mode": mode}
        cached = self.store.operation("create", "create", idempotency_key, request)
        if cached:
            if cached["id"] in self.sessions:
                self.current_id = cached["id"]
                self.store.set_current(self.current_id)
            return cached
        if mode not in {"local", "kafka", "flink"}:
            raise ValueError("回放通道只支持 local、kafka 或 flink")
        if mode == "kafka" and not self.config.kafka.get("enabled", False):
            raise ValueError("Kafka 事件通道尚未启用，请检查本地配置和 broker")
        if mode == "flink" and not (self.config.kafka.get("enabled", False) and self.config.flink.get("enabled", False)):
            raise ValueError("Flink 通道需要同时启用 Kafka 和 Flink，并运行日窗口作业")
        dates = self.catalog.dates_between(start, end)
        session_id = uuid4().hex[:12]
        session = ReplaySession(session_id, dates, speed, self.catalog, self.config, self.store, mode)
        session.clock.set_speed(speed)
        self.sessions[session_id] = session
        self.current_id = session_id
        snapshot = session.snapshot()
        self.store.save_session(snapshot)
        self.store.set_current(session_id)
        self.store.save_operation("create", "create", idempotency_key, request, snapshot)
        return snapshot

    def get(self, session_id: str) -> ReplaySession:
        try:
            return self.sessions[session_id]
        except KeyError as error:
            raise KeyError("回放会话不存在") from error

    def current(self) -> dict[str, Any] | None:
        return self.sessions[self.current_id].snapshot() if self.current_id else None

    def results(self, session_id: str, after: int, limit: int) -> dict[str, Any]:
        self.get(session_id)
        return self.store.results(session_id, after, limit)

    async def close(self) -> None:
        await asyncio.gather(*(session.close() for session in self.sessions.values()))
        self.store.close()
