from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ReplayCreateRequest(BaseModel):
    start_date: date
    end_date: date
    speed: float = 1.0
    mode: Literal["local", "kafka", "flink"] = "local"


class ReplaySpeedRequest(BaseModel):
    speed: float


class RuleRequest(BaseModel):
    model_config = {"extra": "forbid"}
    volatility_quantile: float = Field(ge=0.5, le=0.99)
    correlation_quantile: float = Field(ge=0.5, le=0.99)
    minimum_history: int = Field(ge=10, le=1000)
    regime_change_enabled: bool = True
