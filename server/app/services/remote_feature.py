from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.core.config import AppConfig
from app.core.observability import current_request_id
from app.core.auth import outgoing_auth_headers
from app.services.catalog_factory import create_catalog_reader


class FeatureServiceError(RuntimeError):
    pass


class RemoteFeatureClient:
    def __init__(self, base_url: str, timeout_seconds: float = 10, opener: Callable[..., Any] = urlopen):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("FEATURE_SERVICE_URL 必须是有效的 HTTP 地址")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("特征服务超时必须大于 0 秒")
        self.opener = opener

    def get(self, path: str) -> Any:
        request = Request(self.base_url + path, headers={"Accept": "application/json", "X-Request-ID": current_request_id(), **outgoing_auth_headers()})
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
            raise FeatureServiceError("特征与状态服务暂时不可用") from error

    def close(self) -> None:
        pass


class RemoteFeatureService:
    def __init__(self, config: AppConfig, opener: Callable[..., Any] = urlopen):
        self.storage_mode = config.storage_mode
        self.feature = RemoteFeatureClient(config.feature_service["url"], config.feature_service["timeout_seconds"], opener)
        self.catalog = create_catalog_reader(config)

    def assets(self) -> list[dict[str, Any]]:
        return self.feature.get("/api/assets")

    def latest_state(self) -> dict[str, Any]:
        return self.feature.get("/api/regimes/latest")

    def feature_cache_status(self) -> dict[str, Any]:
        return self.feature.get("/api/system/feature-cache")

    def health_details(self) -> dict[str, Any]:
        health = self.feature.get("/api/health")
        return {"storage_mode": health["storage_mode"], "assets": health["assets"], "states": health["states"]}

    def market_readiness(self) -> dict[str, Any]:
        return self.feature.get("/api/health/ready")["checks"]["market"]

    def replay_metrics(self) -> dict[str, int]:
        metrics = self.feature.get("/api/system/metrics")
        return {"replay_sessions": metrics["replay_sessions"], "active_replays": metrics["active_replays"]}

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
        self.feature.close()
        close = getattr(self.catalog, "close", None)
        if close:
            close()
