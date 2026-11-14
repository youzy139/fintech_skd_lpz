from __future__ import annotations

from dataclasses import asdict
from typing import Any, Collection

from app.core.config import AppConfig
from app.services.alert_rules import AlertRuleManager
from app.services.catalog_factory import create_catalog_reader
from app.services.context_evidence import attach_context
from app.services.contracts import CatalogReader
from app.services.remote_feature import RemoteFeatureClient
from market_core.models.alerts import alert_evidence as build_alert_evidence
from market_core.models.alerts import generate_alerts


class AlertService:
    def __init__(self, config: AppConfig, feature: RemoteFeatureClient | None = None, rules: AlertRuleManager | None = None, catalog: CatalogReader | None = None):
        if not config.feature_service["url"] and feature is None:
            raise ValueError("独立预警服务需要 FEATURE_SERVICE_URL")
        self.config = config
        self.feature = feature or RemoteFeatureClient(config.feature_service["url"], config.feature_service["timeout_seconds"])
        self.rule_manager = rules or AlertRuleManager(config.database_path.with_name("alert_rules.sqlite3"), config.alerts)
        self.catalog = catalog or (create_catalog_reader(config) if config.data_service["url"] else None)
        self.states: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.state_count = 0
        self.latest_state_date: str | None = None
        self.initialized = False

    def initialize(self) -> None:
        states = self.feature.get("/api/internal/alert-states")
        if not isinstance(states, list) or not states:
            raise RuntimeError("特征服务尚未产生市场状态")
        self.states = states
        self.state_count = len(states)
        self.latest_state_date = str(states[-1]["date"])
        self.rebuild_alerts()
        self.initialized = True

    def rebuild_alerts(self) -> None:
        current = self.rule_manager.current()
        self.alerts = [asdict(item) for item in generate_alerts(self.states, **current["settings"], rule_version=current["version"])]

    def list_alerts(self, limit: int) -> list[dict[str, Any]]:
        return list(reversed(self.alerts[-limit:]))

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

    def alert_evidence(self, rule: str, event_date: str, allowed_sources: Collection[str] | None = None) -> dict[str, Any]:
        evidence = build_alert_evidence(self.states, self.alerts, rule, event_date, self.rule_manager.current()["settings"])
        return attach_context(evidence, self.catalog, allowed_sources=allowed_sources)

    def health_details(self) -> dict[str, Any]:
        return {"states": self.state_count, "alerts": len(self.alerts), "latest_state_date": self.latest_state_date, "rule_version": self.rule_manager.current()["version"]}

    def readiness(self) -> dict[str, Any]:
        return {"status": "ok" if self.initialized else "unavailable", **self.health_details()}

    def close(self) -> None:
        self.feature.close()
        if self.catalog is not None:
            close = getattr(self.catalog, "close", None)
            if close:
                close()
