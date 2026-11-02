from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.config import AppConfig
from app.services.remote_feature import RemoteFeatureClient
from market_core.models.alerts import generate_alerts


class AlertService:
    def __init__(self, config: AppConfig, feature: RemoteFeatureClient | None = None):
        if not config.feature_service["url"] and feature is None:
            raise ValueError("独立预警服务需要 FEATURE_SERVICE_URL")
        self.config = config
        self.feature = feature or RemoteFeatureClient(config.feature_service["url"], config.feature_service["timeout_seconds"])
        self.alerts: list[dict[str, Any]] = []
        self.state_count = 0
        self.latest_state_date: str | None = None
        self.initialized = False

    def initialize(self) -> None:
        states = self.feature.get("/api/internal/alert-states")
        if not isinstance(states, list) or not states:
            raise RuntimeError("特征服务尚未产生市场状态")
        alerts = [asdict(item) for item in generate_alerts(states, self.config.alerts["volatility_quantile"], self.config.alerts["correlation_quantile"])]
        self.alerts = alerts
        self.state_count = len(states)
        self.latest_state_date = str(states[-1]["date"])
        self.initialized = True

    def list_alerts(self, limit: int) -> list[dict[str, Any]]:
        return list(reversed(self.alerts[-limit:]))

    def health_details(self) -> dict[str, Any]:
        return {"states": self.state_count, "alerts": len(self.alerts), "latest_state_date": self.latest_state_date}

    def readiness(self) -> dict[str, Any]:
        return {"status": "ok" if self.initialized else "unavailable", **self.health_details()}

    def close(self) -> None:
        self.feature.close()
