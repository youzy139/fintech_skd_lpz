from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from market_core.domain.replay import AssetObservation, ReplayDayInput


MARKET_DAY_EVENT = "market.replay.day.v1"


@dataclass(frozen=True)
class MarketDayEvent:
    event_id: str
    session_id: str
    run_id: str
    event_date: date
    replay_time: str
    observations: tuple[AssetObservation, ...]
    schema_version: int = 1
    event_type: str = MARKET_DAY_EVENT
    source: str = "sqlite.asset-catalog"

    @classmethod
    def from_batch(cls, session_id: str, run_id: str, batch: ReplayDayInput) -> MarketDayEvent:
        return cls(
            event_id=f"{session_id}:{run_id}:{batch.event_date.isoformat()}",
            session_id=session_id,
            run_id=run_id,
            event_date=batch.event_date,
            replay_time=datetime.now(timezone.utc).isoformat(),
            observations=batch.observations,
        )

    def to_batch(self) -> ReplayDayInput:
        return ReplayDayInput(self.event_date, self.observations, self.event_id, self.replay_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "event_time": self.event_date.isoformat(),
            "replay_time": self.replay_time,
            "source": self.source,
            "payload": {
                "observations": [
                    {"code": item.code, "event_date": item.event_date.isoformat(), "value": item.value}
                    for item in self.observations
                ]
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MarketDayEvent:
        if payload.get("schema_version") != 1 or payload.get("event_type") != MARKET_DAY_EVENT:
            raise ValueError("不支持的行情事件结构或版本")
        event_date = date.fromisoformat(payload["event_time"])
        observations = tuple(
            AssetObservation(item["code"], date.fromisoformat(item["event_date"]), float(item["value"]))
            for item in payload["payload"]["observations"]
        )
        if not payload.get("event_id") or not payload.get("session_id") or not payload.get("run_id"):
            raise ValueError("行情事件缺少会话或事件标识")
        if any(item.event_date != event_date or not math.isfinite(item.value) for item in observations):
            raise ValueError("行情事件包含跨日期或非法数值")
        datetime.fromisoformat(payload["replay_time"])
        return cls(
            event_id=payload["event_id"],
            session_id=payload["session_id"],
            run_id=payload["run_id"],
            event_date=event_date,
            replay_time=payload["replay_time"],
            observations=observations,
            source=payload.get("source", "unknown"),
        )
