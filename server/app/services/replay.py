from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import asdict
from datetime import date
from time import monotonic
from typing import Any
from uuid import uuid4

import pandas as pd
from anyio import CancelScope
from redis.exceptions import RedisError

from app.core.config import AppConfig
from app.core.leases import ConnectionLeases
from app.core.observability import log_event
from app.core.serialization import json_compatible
from app.services.flink import FlinkReplayPipeline
from app.services.kafka import KafkaReplayPipeline
from app.services.replay_store import ReplayStore
from app.services.replay_capacity import ReplayLeaseLost, acquire, lease_call, serialized_control
from market_core.domain.replay import AssetObservation, ReplayClock, ReplayDayInput, ReplayDayResult
from market_core.models.replay import HistoricalMarketReplay
from market_core.models.regime import LEGACY_IDENTITY, REGIME_IDENTITY
from market_core.models.feature_contracts import content_version, feature_contract, market_input_version, model_parameters

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
        self.input_versions: dict[date, str] = {}

    def input_version(self, through: date) -> str:
        if through not in self.input_versions:
            self.input_versions[through] = market_input_version(self.series, through)
        return self.input_versions[through]

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
    def __init__(self, session_id: str, dates: tuple[date, ...], speed: float, catalog: ReplayDataCatalog, config: AppConfig, store: ReplayStore, mode: str = "local", capacity=None):
        self.id = session_id
        self.mode = mode
        self.clock = ReplayClock(dates, speed)
        self.catalog = catalog
        self.config = config
        self.model_identity = config.model.get("regime_identity", REGIME_IDENTITY)
        self.calculation_contract = None
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
        self.capacity = capacity or ConnectionLeases(per_user=1, total=2)
        self.control_lock = asyncio.Lock()
        self.compute_lease = None
        self.lease_deadline = 0.0
        self.lease_lost = False
        self.owner_token = None
        self.cleaning_up = False

    async def reserve(self) -> None:
        self.compute_lease, self.lease_deadline = await acquire(self.capacity, self.id)
        self.lease_lost = False
        try:
            self.owner_token = self.compute_lease.token
            self.store.claim(self.id, self.owner_token)
            stored = self.store.load_session(self.id)
            if stored:
                self.restore(stored)
            self.engine = None
            self.restore_latest()
        except BaseException:
            await self.release()
            raise

    def restore_latest(self) -> None:
        latest = self.store.latest_result(self.id)
        self.latest_result = None
        if latest:
            result = latest[1]
            result["observed_assets"] = tuple(result["observed_assets"])
            result["alerts"] = tuple(result["alerts"])
            self.latest_result = ReplayDayResult(**result)

    def require_lease(self) -> None:
        if self.lease_lost or monotonic() >= self.lease_deadline or not self.store.owns(self.id, self.owner_token):
            raise ReplayLeaseLost("回放资源租约失效，已暂停；服务恢复后可继续")

    async def release(self) -> None:
        lease, self.compute_lease = self.compute_lease, None
        if lease:
            try:
                await lease_call(self.capacity, self.capacity.release, lease)
            except (RedisError, TimeoutError):
                replay_logger.warning("replay_lease_release_failed session_id=%s", self.id)

    async def keep_lease(self) -> None:
        while True:
            await asyncio.sleep(self.capacity.ttl / 3)
            deadline = monotonic() + self.capacity.ttl
            try:
                if not await lease_call(self.capacity, self.capacity.renew, self.compute_lease):
                    self.lease_lost = True
                    return
                self.lease_deadline = deadline
            except (RedisError, TimeoutError):
                self.lease_lost = True
                return

    async def compute(self, method, *args):
        # Cancelling to_thread does not stop its worker. Drain it before releasing
        # capacity or allowing restart to replace the engine.
        work = asyncio.create_task(asyncio.to_thread(method, *args))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await asyncio.gather(work, return_exceptions=True)
            raise

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
        return json_compatible({
            "id": self.id,
            "run_id": self.run_id,
            "flink_job_id": self.flink_job_id,
            "savepoint_path": self.savepoint_path,
            "mode": self.mode,
            "model_identity": self.model_identity,
            "calculation_contract": deepcopy(self.calculation_contract),
            "lineage_status": "pinned" if self.calculation_contract else "legacy-unpinned",
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
        })

    def persist(self) -> None:
        self.store.save_session(self.snapshot(), self.owner_token)

    def operation(self, action: str, key: str | None, request: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.store.operation(self.id, action, key, request or {})

    def save_operation(self, action: str, key: str | None, request: dict[str, Any] | None = None) -> None:
        self.store.save_operation(self.id, action, key, request or {}, self.snapshot(), self.owner_token)

    def restore(self, stored: dict[str, Any]) -> None:
        self.model_identity = stored.get("model_identity", LEGACY_IDENTITY)
        self.calculation_contract = deepcopy(stored.get("calculation_contract"))
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
        self.recovery_pending = False
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

    @serialized_control
    async def start(self, idempotency_key: str | None = None) -> dict[str, Any]:
        return await self._start(idempotency_key)

    async def _start(self, idempotency_key: str | None = None, reserved=False) -> dict[str, Any]:
        async with self.lock:
            cached = self.operation("start", idempotency_key)
            if cached:
                return cached
            if self.clock.status == "running" and self.task and not self.task.done():
                return self.snapshot()
            if self.clock.status != "pending":
                raise ValueError("仅待开始的回放可以启动，暂停会话请使用继续")
            if not reserved:
                await self.reserve()
            try:
                self.clock.start()
                self.resumed.set()
                await self.status_message()
                self.cleaning_up = False
                self.task = asyncio.create_task(self._run())
                snapshot = self.snapshot()
                self.save_operation("start", idempotency_key)
                return snapshot
            except BaseException:
                if not self.task or self.task.done():
                    await self.release()
                raise

    @serialized_control
    async def pause(self, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.lock:
            cached = self.operation("pause", idempotency_key)
            if cached:
                return cached
            if self.clock.status != "paused":
                self.clock.pause()
            self.resumed.clear()
            await self.status_message()
        # The current event finishes under self.lock. Stop idle waits and close
        # the pipeline before releasing capacity and acknowledging the pause.
        await self.stop_task()
        async with self.lock:
            self.save_operation("pause", idempotency_key)
            return self.snapshot()

    @serialized_control
    async def resume(self, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.lock:
            cached = self.operation("resume", idempotency_key)
            if cached:
                return cached
            if self.clock.status == "running" and self.task and not self.task.done():
                return self.snapshot()
            if self.clock.status != "paused":
                raise ValueError("仅暂停的回放可以继续")
            await self.reserve()
            try:
                self.clock.resume()
                self.clock.error = None
                if self.recovery_pending:
                    self.recovery_state = "rebuilding"
                    self.recovery_count += 1
                self.resumed.set()
                await self.status_message()
                self.cleaning_up = False
                self.task = asyncio.create_task(self._run())
                snapshot = self.snapshot()
                self.save_operation("resume", idempotency_key)
                return snapshot
            except BaseException:
                if not self.task or self.task.done():
                    await self.release()
                raise

    @serialized_control
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

    @serialized_control
    async def restart(self, idempotency_key: str | None = None) -> dict[str, Any]:
        async with self.restart_lock:
            cached = self.operation("restart", idempotency_key)
            if cached:
                return cached
            await self.stop_task()
            await self.reserve()
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
                self.store.reset_session(snapshot, self.owner_token)
                await self.publish({"type": "replay_reset", "session": snapshot})
            snapshot = await self._start(reserved=True)
            self.save_operation("restart", idempotency_key)
            return snapshot

    def pin_calculation(self) -> None:
        model = model_parameters(self.config.model)
        # Replay v1 historically uses these two quantiles and rule defaults.
        alerts = {name: float(self.config.alerts[name]) for name in ("volatility_quantile", "correlation_quantile")}
        payload = {
            "schema_version": 1,
            "model": model,
            "alerts": alerts,
            "feature_contract": feature_contract(model),
            "input_version": self.catalog.input_version(self.clock.dates[-1]),
            "input_through": self.clock.dates[-1].isoformat(),
        }
        self.calculation_contract = {**payload, "version": content_version("calculation-", payload)}

    def _build_engine(self) -> HistoricalMarketReplay:
        if self.calculation_contract:
            contract = self.calculation_contract
            payload = {key: value for key, value in contract.items() if key != "version"}
            if contract.get("schema_version") != 1 or contract.get("version") != content_version("calculation-", payload):
                raise ValueError("回放计算契约校验失败，请创建新会话")
            settings = deepcopy(contract["model"])
            if settings.get("regime_identity") != self.model_identity or feature_contract(settings) != contract["feature_contract"]:
                raise ValueError("回放特征或身份算法契约已改变，请使用兼容版本或创建新会话")
            if contract["input_through"] != self.clock.dates[-1].isoformat() or contract["input_version"] != self.catalog.input_version(self.clock.dates[-1]):
                raise ValueError("回放输入已改变，拒绝混合历史结果；请创建新会话")
            alerts = deepcopy(contract["alerts"])
        else:
            settings = {**self.config.model, "regime_identity": self.model_identity}
            alerts = self.config.alerts
        engine = HistoricalMarketReplay(self.catalog.series, settings, alerts, self.clock.dates[0])
        for event_date in self.clock.dates[:self.clock.position]:
            engine.advance(self.catalog.read(event_date))
        return engine

    async def _run(self) -> None:
        self.cleaning_up = False
        pipeline = None
        keeper = asyncio.create_task(self.keep_lease())
        try:
            self.require_lease()
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
            if self.mode == "flink":
                pipeline.savepoint_path = self.savepoint_path
            self.pipeline = pipeline
            self.run_id = getattr(pipeline, "run_id", None) or self.run_id or uuid4().hex
            async with self.lock:
                if self.engine is None:
                    engine_started = monotonic()
                    self.engine = await self.compute(self._build_engine)
                    self.require_lease()
                    self.engine_start_ms = (monotonic() - engine_started) * 1000
                    if self.clock.position and self.recovery_pending:
                        self.rebuild_ms = self.engine_start_ms
                    self.recovery_pending = False
                    if self.recovery_state == "rebuilding":
                        self.recovery_state = "completed"
                pipeline_started = monotonic()
                await pipeline.start()
                self.require_lease()
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
                    self.require_lease()
                    event_date = self.clock.advance()
                    day_started = monotonic()
                    batch = await pipeline.next(event_date)
                    input_finished = monotonic()
                    self.require_lease()
                    self.latest_result = await self.compute(self.engine.advance, batch)
                    self.require_lease()
                    model_finished = monotonic()
                    await pipeline.ack(batch)
                    self.require_lease()
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
                    result = json_compatible(asdict(self.latest_result))
                    self.store.record_result(self.snapshot(), self.latest_sequence, result, self.owner_token)
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
                    # Poll only the cancellation/lease flag during long pacing.
                    remaining = self.config.replay["interval_ms"] / 1000 / self.clock.speed
                    while remaining > 0:
                        step = min(remaining, self.capacity.ttl / 3)
                        await asyncio.sleep(step)
                        remaining -= step
                        self.require_lease()
        except asyncio.CancelledError:
            self.clock.position = self.timed_days
            if self.clock.status == "running":
                self.clock.pause()
            self.engine = None
            self.restore_latest()
            raise
        except ReplayLeaseLost as error:
            async with self.lock:
                self.clock.position = self.timed_days
                self.clock.status = "paused"
                self.clock.error = str(error)
                self.engine = None
                self.restore_latest()
                self.recovery_pending = True
                self.recovery_state = "paused"
                if self.store.owns(self.id, self.owner_token):
                    await self.status_message("replay_error")
        except Exception as error:
            async with self.lock:
                if self.recovery_state == "rebuilding":
                    self.recovery_state = "failed"
                if self.clock.status not in {"completed", "failed"}:
                    self.clock.fail(str(error))
                await self.status_message("replay_error")
        finally:
            self.cleaning_up = True
            cleanup = asyncio.create_task(self.finish_run(pipeline, keeper))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                with CancelScope(shield=True):
                    await asyncio.gather(cleanup, return_exceptions=True)
                raise

    async def finish_run(self, pipeline, keeper) -> None:
        with CancelScope(shield=True):
            try:
                if pipeline:
                    self.event_stats = dict(pipeline.stats)
                    try:
                        await pipeline.close()
                    except Exception as error:
                        self.clock.status = "failed"
                        self.clock.error = f"回放通道关闭失败：{error}"
                        if self.store.owns(self.id, self.owner_token):
                            await self.status_message("replay_error")
                    finally:
                        self.pipeline_timing = dict(getattr(pipeline, "timing", {}))
                        self.flink_job_id = getattr(pipeline, "flink_job_id", None)
                        self.savepoint_path = getattr(pipeline, "savepoint_path", None) or self.savepoint_path
                if self.clock.status == "paused":
                    self.recovery_pending = self.engine is None
                    self.recovery_state = "paused" if self.recovery_pending else self.recovery_state
                if self.store.owns(self.id, self.owner_token):
                    await self.status_message()
            finally:
                self.pipeline = None
                keeper.cancel()
                await asyncio.gather(keeper, return_exceptions=True)
                await self.release()

    async def stop_task(self) -> None:
        if self.task and not self.task.done():
            if not self.cleaning_up:
                self.task.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(self.task, return_exceptions=True)
        self.task = None
        # A task cancelled before its coroutine starts has no finally block.
        if self.compute_lease:
            if self.clock.status == "running":
                self.clock.status = "paused"
                self.clock.position = self.timed_days
                self.engine = None
            if self.store.owns(self.id, self.owner_token):
                self.persist()
            await self.release()

    @serialized_control
    async def close(self) -> None:
        await self.stop_task()
        self.subscribers.clear()


class ReplayManager:
    def __init__(self, service, config: AppConfig, store: ReplayStore | None = None, capacity=None):
        self.catalog = ReplayDataCatalog(service.series)
        self.config = config
        self.store = store or ReplayStore(config.database_path)
        self.capacity = capacity or ConnectionLeases(per_user=1, total=2)
        self.sessions: dict[str, ReplaySession] = {}
        for stored in self.store.load_sessions():
            dates = self.catalog.dates_between(date.fromisoformat(stored["start_date"]), date.fromisoformat(stored["end_date"]))
            session = ReplaySession(stored["id"], dates, stored["speed"], self.catalog, self.config, self.store, stored["mode"], self.capacity)
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
        session = ReplaySession(session_id, dates, speed, self.catalog, self.config, self.store, mode, self.capacity)
        session.clock.set_speed(speed)
        session.pin_calculation()
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
