from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class ReplayCreateRequest(BaseModel):
    start_date: date
    end_date: date
    speed: float = 1.0
    mode: Literal["local", "kafka", "flink"] = "local"


class ReplaySpeedRequest(BaseModel):
    speed: float
