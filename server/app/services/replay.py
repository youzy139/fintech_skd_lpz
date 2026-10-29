from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date
from typing import Any
from uuid import uuid4

import pandas as pd

from app.core.config import AppConfig
from market_core.domain.replay import AssetObservation, ReplayClock, ReplayDayInput, ReplayDayResult
from market_core.models.replay import HistoricalMarketReplay


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
    def __init__(self, session_id: str, dates: tuple[date, ...], speed: float, catalog: ReplayDataCatalog, config: AppConfig):
        self.id = session_id
        self.clock = ReplayClock(dates, speed)
        self.catalog = catalog
        self.config = config
        self.engine: HistoricalMarketReplay | None = None
        self.latest_result: ReplayDayResult | None = None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.resumed = asyncio.Event()
        self.subscribers: set[asyncio.Queue] = set()

    def snapshot(self) -> dict[str, Any]:
        total = len(self.clock.dates)
        return {
            "id": self.id,
            "start_date": self.clock.dates[0].isoformat(),
            "end_date": self.clock.dates[-1].isoformat(),
            "status": self.clock.status,
            "speed": self.clock.speed,
            "processed_days": self.clock.position,
            "total_days": total,
            "current_date": self.clock.current_date.isoformat() if self.clock.current_date else None,
            "progress": self.clock.position / total,
            "error": self.clock.error,
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
            self.latest_result = None
            await self.status_message("replay_reset")
        return await self.start()

    async def _run(self) -> None:
        try:
            async with self.lock:
                if self.engine is None:
                    self.engine = await asyncio.to_thread(HistoricalMarketReplay, self.catalog.series, self.config.model, self.config.alerts, self.clock.dates[0])
            while self.clock.status in {"running", "paused"}:
                if self.clock.status == "paused":
                    await self.resumed.wait()
                    continue
                async with self.lock:
                    if self.clock.status == "paused":
                        continue
                    event_date = self.clock.advance()
                    batch = self.catalog.read(event_date)
                    self.latest_result = await asyncio.to_thread(self.engine.advance, batch)
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

    def create(self, start: date, end: date, speed: float) -> dict[str, Any]:
        dates = self.catalog.dates_between(start, end)
        session_id = uuid4().hex[:12]
        session = ReplaySession(session_id, dates, speed, self.catalog, self.config)
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
