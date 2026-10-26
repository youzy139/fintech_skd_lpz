from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class AssetMeta:
    category: str
    name: str
    code: str
    field: str
    calendar: str
    declared_start: date
    declared_end: date
    declared_rows: int
    source: Path


@dataclass
class AssetSeries:
    meta: AssetMeta
    frame: pd.DataFrame
    duplicate_dates: int = 0
    invalid_rows: int = 0


@dataclass
class DataQuality:
    catalog_records: int
    available_assets: int
    loaded_assets: int
    missing_assets: list[str] = field(default_factory=list)
    duplicate_dates: int = 0
    invalid_rows: int = 0
    total_rows: int = 0


@dataclass(frozen=True)
class Alert:
    date: str
    rule: str
    level: str
    title: str
    evidence: str
    value: float | None = None
    threshold: float | None = None
