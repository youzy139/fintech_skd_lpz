from __future__ import annotations

import csv
import math
from datetime import date
from pathlib import Path

import pandas as pd

from market_core.domain.market import AssetMeta, AssetSeries, DataQuality


class AssetRepository:
    def __init__(self, data_root: Path):
        self.asset_root = data_root / "目标资产价格变量"
        self.catalog_path = self.asset_root / "代码对照.csv"

    def catalog(self) -> list[AssetMeta]:
        assets: list[AssetMeta] = []
        with self.catalog_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["状态"] != "ok":
                    continue
                source = self.asset_root / f"{row['名称']}.csv"
                if not source.is_file():
                    continue
                assets.append(
                    AssetMeta(
                        category=row["大类"],
                        name=row["名称"],
                        code=row["Wind代码"],
                        field=row["字段"],
                        calendar=row["交易日历"],
                        declared_start=date.fromisoformat(row["起始"]),
                        declared_end=date.fromisoformat(row["结束"]),
                        declared_rows=int(row["条数"]),
                        source=source,
                    )
                )
        return assets

    def load(self, meta: AssetMeta) -> AssetSeries:
        observations: dict[date, float] = {}
        duplicates = 0
        invalid = 0
        with meta.source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["date", meta.field]:
                raise ValueError(f"{meta.name} 字段不符合目录约定: {reader.fieldnames}")
            for row in reader:
                try:
                    day = date.fromisoformat(row["date"])
                    value = float(row[meta.field])
                    if not math.isfinite(value):
                        raise ValueError("non-finite observation")
                except (TypeError, ValueError):
                    invalid += 1
                    continue
                if day in observations:
                    duplicates += 1
                observations[day] = value
        frame = pd.DataFrame(
            [(day, value) for day, value in sorted(observations.items())],
            columns=["date", "value"],
        )
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"])
        return AssetSeries(meta=meta, frame=frame, duplicate_dates=duplicates, invalid_rows=invalid)

    def load_all(self) -> tuple[list[AssetSeries], DataQuality]:
        with self.catalog_path.open(encoding="utf-8-sig", newline="") as handle:
            catalog_rows = list(csv.DictReader(handle))
        available = self.catalog()
        loaded = [self.load(meta) for meta in available]
        series = [item for item in loaded if not item.frame.empty]
        available_codes = {meta.code for meta in available}
        quality = DataQuality(
            catalog_records=len(catalog_rows),
            available_assets=len(available),
            loaded_assets=len(series),
            missing_assets=[row["名称"] for row in catalog_rows if row["Wind代码"] not in available_codes],
            duplicate_dates=sum(item.duplicate_dates for item in loaded),
            invalid_rows=sum(item.invalid_rows for item in loaded),
            total_rows=sum(len(item.frame) for item in series),
        )
        return series, quality
