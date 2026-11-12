from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.config import AppConfig
from app.core.serialization import json_compatible
from app.services.alert_rules import AlertRuleManager
from app.services.catalog_factory import create_catalog_reader
from app.services.context_evidence import attach_context
from app.services.cache import RedisJsonCache
from app.services.feature_cache import FeatureSnapshotCache
from app.services.storage import SnapshotStore
from market_core.domain.market import AssetSeries
from market_core.ingestion.assets import AssetRepository
from market_core.models.alerts import alert_evidence, generate_alerts
from market_core.models.feature_contracts import feature_contract, market_input_version, model_parameters
from market_core.models.features import build_market_features
from market_core.models.regime import REGIME_IDENTITY, WalkForwardRegimeModel


class MarketService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.repository = AssetRepository(config.data_root)
        self.series: list[AssetSeries] = []
        self.states: list[dict] = []
        self.alerts: list[dict] = []
        self.quality: dict = {}
        self._feature_metadata: dict[str, Any] = {}
        self._feature_cache = RedisJsonCache.from_config({**config.redis, "namespace": config.redis["namespace"] + ":features:latest:v1"}) if config.redis["enabled"] else None
        self._feature_snapshot: FeatureSnapshotCache | None = None
        self.store = SnapshotStore(config.database_path)
        self.storage_mode = config.storage_mode
        self.catalog = create_catalog_reader(config)
        self.rule_manager = AlertRuleManager(config.database_path.with_name("alert_rules.sqlite3"), config.alerts)

    def initialize(self) -> None:
        self.series, quality = self.repository.load_all()
        if not self.series:
            raise RuntimeError("没有可用资产数据")
        settings = self.config.model
        features = build_market_features(self.series, settings["volatility_window"], settings["momentum_window"], settings["analysis_start"])
        model = WalkForwardRegimeModel(settings["minimum_history"], settings["training_window"], settings["refit_interval"], settings["cluster_count"], settings["random_seed"], settings.get("regime_identity", REGIME_IDENTITY))
        self.states = model.predict(features)
        self._feature_metadata = {
            "feature_contract": feature_contract(settings),
            "model_parameters": model_parameters(settings),
            "data_version": self.catalog.data_version(),
            "input_version": market_input_version(self.series),
            "state_model_version": self.states[-1]["model_version"] if self.states else None,
        }
        self._feature_snapshot = FeatureSnapshotCache(self._feature_metadata, self.latest_state(), self._feature_cache) if self.states else None
        self.rebuild_alerts()
        self.quality = {**asdict(quality), "sources": self.catalog.summary()}
        self.store.save("quality", self.quality)
        self.store.save("states", self.states)

    def rebuild_alerts(self) -> None:
        current = self.rule_manager.current()
        settings = current["settings"]
        self.alerts = [asdict(item) for item in generate_alerts(self.states, **settings, rule_version=current["version"])]
        self.alert_rule_version = current["version"]
        self.store.save("alerts", self.alerts)

    def alert_rules(self) -> dict[str, Any]:
        return self.rule_manager.describe()

    def update_alert_rules(self, settings: dict[str, Any], actor: str) -> dict[str, Any]:
        result = self.rule_manager.save(settings, actor)
        self.rebuild_alerts()
        return result

    def activate_alert_rule(self, version: str, actor: str) -> dict[str, Any]:
        result = self.rule_manager.activate(version, actor)
        self.rebuild_alerts()
        return result

    def alert_evidence(self, rule: str, event_date: str) -> dict[str, Any]:
        evidence = alert_evidence(self.states, self.alerts, rule, event_date, self.rule_manager.current()["settings"])
        return attach_context(evidence, getattr(self, "catalog", None))

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

    def feature_metadata(self) -> dict[str, Any]:
        if not self._feature_metadata:
            raise RuntimeError("特征元数据尚未初始化")
        return json_compatible(self._feature_metadata)

    def latest_features(self) -> dict[str, Any]:
        if self._feature_snapshot is None:
            raise RuntimeError("特征尚未初始化")
        return self._feature_snapshot.read()

    def feature_cache_status(self) -> dict[str, Any]:
        if self._feature_snapshot is None:
            return {"enabled": self._feature_cache is not None, "status": "uninitialized"}
        return self._feature_snapshot.status()

    def alert_states(self) -> list[dict[str, Any]]:
        return json_compatible(self.states)

    def home_summary(self) -> dict[str, Any]:
        if getattr(self, "alert_rule_version", None) != self.rule_manager.current()["version"]:
            self.rebuild_alerts()
        return {
            "latest": self.latest_state(),
            "alert_count": len(self.alerts),
            "loaded_assets": len(self.series),
            "total_rows": self.quality.get("total_rows", 0),
            "state_count": len(self.states),
        }

    def health_details(self) -> dict[str, Any]:
        return {"storage_mode": self.storage_mode, "assets": len(self.series), "states": len(self.states)}

    def market_readiness(self) -> dict[str, Any]:
        ready = bool(self.series and self.states)
        return {"status": "ok" if ready else "unavailable", "assets": len(self.series), "states": len(self.states)}

    def replay_metrics(self) -> dict[str, int]:
        sessions = list(getattr(self, "replay_manager").sessions.values())
        return {"replay_sessions": len(sessions), "active_replays": sum(session.clock.status in {"running", "paused"} for session in sessions)}

    def data_version(self) -> str:
        return self.catalog.data_version()

    def source_summary(self) -> dict[str, Any]:
        return self.catalog.summary()

    def source_overview(self, kind: str | None) -> dict[str, Any]:
        return self.catalog.overview(kind)

    def source_governance(self, kind: str | None) -> dict[str, Any]:
        return self.catalog.governance(kind)

    def source_file_governance(self, source_id: str) -> dict[str, Any] | None:
        return self.catalog.file_governance(source_id)

    def source_tags(self, kind: str | None) -> list[dict[str, Any]]:
        return self.catalog.list_tags(kind)

    def source_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        return self.catalog.list_files(kind, query, offset, limit)

    def source_records(self, source_id: str | None, query: str | None, date: str | None, offset: int, limit: int, kind: str | None = None, tag: str | None = None, tags: list[str] | None = None, match: str = "any") -> dict[str, Any]:
        return self.catalog.list_records(source_id, query, date, offset, limit, kind, tag, tags, match)

    def close(self) -> None:
        self.store.close()
        self.catalog.close()
        if self._feature_cache is not None:
            self._feature_cache.close()
