from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date
from typing import Any
from uuid import uuid4

import pandas as pd

from app.core.config import AppConfig
from app.services.kafka import KafkaReplayPipeline
from market_core.domain.replay import AssetObservation, ReplayClock, ReplayDayInput, ReplayDayResult
from market_core.models.replay import HistoricalMarketReplay


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
        self.event_stats = {"produced_events": 0, "consumed_events": 0, "duplicate_events": 0, "retry_count": 0, "commit_count": 0}
        self.latest_result: ReplayDayResult | None = None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.resumed = asyncio.Event()
        self.subscribers: set[asyncio.Queue] = set()

    def snapshot(self) -> dict[str, Any]:
        total = len(self.clock.dates)
        if self.pipeline:
            self.event_stats = dict(self.pipeline.stats)
        return {
            "id": self.id,
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
            self.event_stats = {key: 0 for key in self.event_stats}
            self.latest_result = None
            await self.status_message("replay_reset")
        return await self.start()

    async def _run(self) -> None:
        pipeline = None
        try:
            if self.mode == "flink":
                settings = {**self.config.kafka, "topic": self.config.flink["output_topic"], "produce_topic": self.config.kafka["topic"], "read_committed": True, "emit_end_of_input": True}
                pipeline = KafkaReplayPipeline(self.id, self.clock.dates, self.catalog, settings)
            elif self.mode == "kafka":
                pipeline = KafkaReplayPipeline(self.id, self.clock.dates, self.catalog, self.config.kafka)
            else:
                pipeline = LocalReplayPipeline(self.clock.dates, self.catalog)
            self.pipeline = pipeline
            async with self.lock:
                if self.engine is None:
                    self.engine = await asyncio.to_thread(HistoricalMarketReplay, self.catalog.series, self.config.model, self.config.alerts, self.clock.dates[0])
                await pipeline.start()
            while self.clock.status in {"running", "paused"}:
                if self.clock.status == "paused":
                    await self.resumed.wait()
                    continue
                async with self.lock:
                    if self.clock.status == "paused":
                        continue
                    event_date = self.clock.advance()
                    batch = await pipeline.next(event_date)
                    self.latest_result = await asyncio.to_thread(self.engine.advance, batch)
                    await pipeline.ack(batch)
                    if self.clock.position == len(self.clock.dates):
                        self.clock.complete()
                    await self.publish({"type": "replay_day", "session": self.snapshot(), "result": asdict(self.latest_result)})
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
                await pipeline.close()
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
