from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal


ReplayStatus = Literal["pending", "running", "paused", "completed", "failed"]


@dataclass
class ReplayClock:
    dates: tuple[date, ...]
    speed: float = 1.0
    status: ReplayStatus = "pending"
    position: int = 0
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.dates:
            raise ValueError("回放范围内没有可处理的交易日")
        if self.dates != tuple(sorted(set(self.dates))):
            raise ValueError("回放日期必须严格递增且不能重复")
        self.set_speed(self.speed)

    @property
    def current_date(self) -> date | None:
        if not self.position:
            return None
        return self.dates[min(self.position, len(self.dates)) - 1]

    def _require(self, expected: ReplayStatus) -> None:
        if self.status != expected:
            raise ValueError(f"当前状态 {self.status} 不允许该操作，需要状态 {expected}")

    def start(self) -> None:
        self._require("pending")
        self.status = "running"
        self.error = None

    def pause(self) -> None:
        self._require("running")
        self.status = "paused"

    def resume(self) -> None:
        self._require("paused")
        self.status = "running"

    def set_speed(self, speed: float) -> None:
        if speed not in {0.5, 1.0, 2.0, 5.0, 10.0}:
            raise ValueError("回放速度只支持 0.5、1、2、5、10 倍")
        self.speed = speed

    def advance(self) -> date:
        self._require("running")
        if self.position >= len(self.dates):
            raise ValueError("回放已经到达末尾")
        current = self.dates[self.position]
        self.position += 1
        return current

    def complete(self) -> None:
        self._require("running")
        if self.position != len(self.dates):
            raise ValueError("尚有回放日期未处理，不能标记为完成")
        self.status = "completed"

    def fail(self, message: str) -> None:
        if self.status in {"completed", "failed"}:
            raise ValueError(f"当前状态 {self.status} 不能标记为失败")
        self.status = "failed"
        self.error = message

    def restart(self) -> None:
        self.status = "pending"
        self.position = 0
        self.error = None


@dataclass(frozen=True)
class AssetObservation:
    code: str
    event_date: date
    value: float


@dataclass(frozen=True)
class ReplayDayInput:
    event_date: date
    observations: tuple[AssetObservation, ...]


@dataclass(frozen=True)
class ReplayDayResult:
    event_time: str
    replay_time: str
    input_start: str
    input_end: str
    input_records: int
    observed_assets: tuple[str, ...]
    features: dict[str, float] = field(default_factory=dict)
    state: dict[str, Any] | None = None
    alerts: tuple[dict[str, Any], ...] = ()
    model_version: str = "walk-forward-warm-up"
