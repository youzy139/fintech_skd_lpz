from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.config import AppConfig
from app.services.catalog import CatalogStore
from app.services.storage import SnapshotStore
from market_core.domain.market import AssetSeries
from market_core.ingestion.assets import AssetRepository
from market_core.models.alerts import generate_alerts
from market_core.models.features import build_market_features
from market_core.models.regime import WalkForwardRegimeModel


class MarketService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.repository = AssetRepository(config.data_root)
        self.series: list[AssetSeries] = []
        self.states: list[dict] = []
        self.alerts: list[dict] = []
        self.quality: dict = {}
        self.store = SnapshotStore(config.database_path)
        self.catalog = CatalogStore(config.database_path)

    def initialize(self) -> None:
        self.series, quality = self.repository.load_all()
        if not self.series:
            raise RuntimeError("没有可用资产数据")
        settings = self.config.model
        features = build_market_features(self.series, settings["volatility_window"], settings["momentum_window"], settings["analysis_start"])
        model = WalkForwardRegimeModel(settings["minimum_history"], settings["training_window"], settings["refit_interval"], settings["cluster_count"], settings["random_seed"])
        self.states = model.predict(features)
        self.alerts = [asdict(item) for item in generate_alerts(self.states, self.config.alerts["volatility_quantile"], self.config.alerts["correlation_quantile"])]
        self.quality = {**asdict(quality), "sources": self.catalog.summary()}
        self.store.save("quality", self.quality)
        self.store.save("states", self.states)
        self.store.save("alerts", self.alerts)

    def assets(self) -> list[dict]:
        return [{"category": item.meta.category, "name": item.meta.name, "code": item.meta.code, "field": item.meta.field, "calendar": item.meta.calendar, "start": item.frame["date"].min().strftime("%Y-%m-%d"), "end": item.frame["date"].max().strftime("%Y-%m-%d"), "rows": len(item.frame)} for item in self.series]

    def asset_series(self, code: str, limit: int) -> dict:
        item = next((entry for entry in self.series if entry.meta.code == code), None)
        if item is None:
            raise KeyError(code)
        frame = item.frame.tail(limit)
        return {"code": code, "name": item.meta.name, "field": item.meta.field, "unit": "percent" if item.meta.field == "yield" else "source_close", "points": [{"date": day.strftime("%Y-%m-%d"), "value": float(value)} for day, value in zip(frame["date"], frame["value"])]}

    def latest_state(self) -> dict:
        if not self.states:
            raise RuntimeError("状态模型尚未初始化")
        return self.states[-1]

    def source_summary(self) -> dict[str, Any]:
        return self.catalog.summary()

    def source_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        return self.catalog.list_files(kind, query, offset, limit)

    def source_records(self, source_id: str, query: str | None, date: str | None, offset: int, limit: int) -> dict[str, Any]:
        return self.catalog.list_records(source_id, query, date, offset, limit)

    def close(self) -> None:
        self.store.close()
        self.catalog.close()
