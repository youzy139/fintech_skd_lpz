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
    def __init__(self, session_id: str, dates: tuple[date, ...], speed: float, catalog: ReplayDataCatalog, config: AppConfig, mode: str = "local"):
        self.id = session_id
        self.mode = mode
        self.clock = ReplayClock(dates, speed)
        self.catalog = catalog
        self.config = config
        self.engine: HistoricalMarketReplay | None = None
        self.pipeline = None
        self.run_id: str | None = None
        self.flink_job_id: str | None = None
        self.savepoint_path: str | None = None
        self.event_stats = {"produced_events": 0, "consumed_events": 0, "duplicate_events": 0, "retry_count": 0, "commit_count": 0}
        self.latest_result: ReplayDayResult | None = None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.resumed = asyncio.Event()
        self.subscribers: set[asyncio.Queue] = set()
        self.pipeline_timing: dict[str, float] = {}
        self.engine_start_ms: float | None = None
        self.pipeline_start_ms: float | None = None
        self.last_day_timing: dict[str, Any] | None = None
        self.timed_days = 0
        self.total_day_ms = 0.0
        self.max_day_ms = 0.0

    def snapshot(self) -> dict[str, Any]:
        total = len(self.clock.dates)
        if self.pipeline:
            self.event_stats = dict(self.pipeline.stats)
            self.pipeline_timing = dict(getattr(self.pipeline, "timing", {}))
            self.flink_job_id = getattr(self.pipeline, "flink_job_id", None)
            self.savepoint_path = getattr(self.pipeline, "savepoint_path", None)
        last_day = None
        if self.last_day_timing:
            last_day = {key: round(value, 3) if isinstance(value, float) else value for key, value in self.last_day_timing.items()}
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
            "processed_days": self.clock.position,
            "total_days": total,
            "current_date": self.clock.current_date.isoformat() if self.clock.current_date else None,
            "progress": self.clock.position / total,
            "error": self.clock.error,
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

    async def publish(self, message: dict[str, Any]) -> None:
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)

    async def status_message(self, message_type: str = "replay_status") -> None:
        await self.publish({"type": message_type, "session": self.snapshot()})

    async def start(self) -> dict[str, Any]:
        async with self.lock:
            self.clock.start()
            self.resumed.set()
            await self.status_message()
            self.task = asyncio.create_task(self._run())
        return self.snapshot()

    async def pause(self) -> dict[str, Any]:
        async with self.lock:
            self.clock.pause()
            self.resumed.clear()
            await self.status_message()
        return self.snapshot()

    async def resume(self) -> dict[str, Any]:
        async with self.lock:
            self.clock.resume()
            self.resumed.set()
            await self.status_message()
        return self.snapshot()

    async def set_speed(self, speed: float) -> dict[str, Any]:
        async with self.lock:
            self.clock.set_speed(speed)
            await self.status_message()
        return self.snapshot()

    async def restart(self) -> dict[str, Any]:
        task = self.task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.lock:
            self.clock.restart()
            self.engine = None
            self.pipeline = None
            self.run_id = None
            self.flink_job_id = None
            self.savepoint_path = None
            self.event_stats = {key: 0 for key in self.event_stats}
            self.latest_result = None
            self.pipeline_timing = {}
            self.engine_start_ms = None
            self.pipeline_start_ms = None
            self.last_day_timing = None
            self.timed_days = 0
            self.total_day_ms = 0.0
            self.max_day_ms = 0.0
            await self.status_message("replay_reset")
        return await self.start()

    async def _run(self) -> None:
        pipeline = None
        try:
            if self.mode == "flink":
                settings = {**self.config.kafka, "topic": self.config.flink["output_topic"], "produce_topic": self.config.kafka["topic"], "read_committed": True, "emit_end_of_input": True}
                pipeline = FlinkReplayPipeline(self.id, self.clock.dates, self.catalog, settings, self.config.flink)
            elif self.mode == "kafka":
                pipeline = KafkaReplayPipeline(self.id, self.clock.dates, self.catalog, self.config.kafka)
            else:
                pipeline = LocalReplayPipeline(self.clock.dates, self.catalog)
            self.pipeline = pipeline
            self.run_id = getattr(pipeline, "run_id", uuid4().hex)
            async with self.lock:
                if self.engine is None:
                    engine_started = monotonic()
                    self.engine = await asyncio.to_thread(HistoricalMarketReplay, self.catalog.series, self.config.model, self.config.alerts, self.clock.dates[0])
                    self.engine_start_ms = (monotonic() - engine_started) * 1000
                pipeline_started = monotonic()
                await pipeline.start()
                self.pipeline_start_ms = (monotonic() - pipeline_started) * 1000
                self.pipeline_timing = dict(getattr(pipeline, "timing", {}))
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
                    self.total_day_ms += self.last_day_timing["total_ms"]
                    self.max_day_ms = max(self.max_day_ms, self.last_day_timing["total_ms"])
                    self.pipeline_timing = dict(getattr(pipeline, "timing", {}))
                    if self.clock.position == len(self.clock.dates):
                        self.clock.complete()
                    await self.publish({"type": "replay_day", "session": self.snapshot(), "result": asdict(self.latest_result)})
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
                    self.savepoint_path = getattr(pipeline, "savepoint_path", None)
                await self.status_message()
            self.pipeline = None

    async def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.subscribers.clear()


class ReplayManager:
    def __init__(self, service, config: AppConfig):
        self.catalog = ReplayDataCatalog(service.series)
        self.config = config
        self.sessions: dict[str, ReplaySession] = {}
        self.current_id: str | None = None

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

    def create(self, start: date, end: date, speed: float, mode: str = "local") -> dict[str, Any]:
        if mode not in {"local", "kafka", "flink"}:
            raise ValueError("回放通道只支持 local、kafka 或 flink")
        if mode == "kafka" and not self.config.kafka.get("enabled", False):
            raise ValueError("Kafka 事件通道尚未启用，请检查本地配置和 broker")
        if mode == "flink" and not (self.config.kafka.get("enabled", False) and self.config.flink.get("enabled", False)):
            raise ValueError("Flink 通道需要同时启用 Kafka 和 Flink，并运行日窗口作业")
        dates = self.catalog.dates_between(start, end)
        session_id = uuid4().hex[:12]
        session = ReplaySession(session_id, dates, speed, self.catalog, self.config, mode)
        session.clock.set_speed(speed)
        self.sessions[session_id] = session
        self.current_id = session_id
        return session.snapshot()

    def get(self, session_id: str) -> ReplaySession:
        try:
            return self.sessions[session_id]
        except KeyError as error:
            raise KeyError("回放会话不存在") from error

    def current(self) -> dict[str, Any] | None:
        return self.sessions[self.current_id].snapshot() if self.current_id else None

    async def close(self) -> None:
        await asyncio.gather(*(session.close() for session in self.sessions.values()))
