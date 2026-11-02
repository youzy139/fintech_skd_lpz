from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.core.observability import current_request_id
from app.core.auth import outgoing_auth_headers


class AlertServiceError(RuntimeError):
    pass


class RemoteAlertClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5, opener: Callable[..., Any] = urlopen):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ALERT_SERVICE_URL 必须是有效的 HTTP 地址")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("预警服务超时必须大于 0 秒")
        self.opener = opener

    def get(self, path: str) -> Any:
        request = Request(self.base_url + path, headers={"Accept": "application/json", "X-Request-ID": current_request_id(), **outgoing_auth_headers()})
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
            raise AlertServiceError("预警服务暂时不可用") from error

    def readiness(self) -> dict[str, Any]:
        return self.get("/api/health/ready")["checks"]["alerts"]

    def close(self) -> None:
        pass
