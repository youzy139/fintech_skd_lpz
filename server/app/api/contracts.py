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


class ResearchWorkspaceRequest(BaseModel):
    model_config = {"extra": "forbid"}
    search: str = Field(default="", max_length=100)
    category: str = Field(default="all", min_length=1, max_length=100)
    watchlist_only: bool = False
    watchlist: list[str] = Field(default_factory=list, max_length=100)
    selected_asset: str = Field(default="", max_length=200)
    visible_range: Literal[60, 250, 500] = 500
