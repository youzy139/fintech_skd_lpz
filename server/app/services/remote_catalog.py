from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from app.core.observability import current_request_id
from app.core.auth import outgoing_auth_headers


class DataServiceError(RuntimeError):
    pass


class RemoteCatalogClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5, opener: Callable[..., Any] = urlopen):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("DATA_SERVICE_URL 必须是有效的 HTTP 地址")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("数据服务超时必须大于 0 秒")
        self.opener = opener

    def _get(self, path: str, parameters: dict[str, Any] | None = None) -> Any:
        query = urlencode([(key, value) for key, values in (parameters or {}).items() for value in (values if isinstance(values, list) else [values]) if value is not None], doseq=True)
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        request = Request(url, headers={"Accept": "application/json", "X-Request-ID": current_request_id(), **outgoing_auth_headers()})
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
            raise DataServiceError("数据服务暂时不可用") from error

    @property
    def cache_stats(self) -> dict[str, Any]:
        return self._get("/api/health").get("catalog_cache", {"shared": {"enabled": False}, "local": {"enabled": False}})

    def data_version(self) -> str:
        return self._get("/api/data/version")["data_version"]

    def summary(self) -> dict[str, Any]:
        return self._get("/api/data/summary")

    def overview(self, kind: str | None) -> dict[str, Any]:
        return self._get("/api/data/overview", {"kind": kind})

    def governance(self, kind: str | None) -> dict[str, Any]:
        return self._get("/api/data/governance", {"kind": kind})

    def list_tags(self, kind: str | None) -> list[dict[str, Any]]:
        return self._get("/api/data/tags", {"kind": kind})

    def list_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        return self._get("/api/data/files", {"kind": kind, "query": query, "offset": offset, "limit": limit})

    def list_records(self, source_id: str | None, query: str | None, date: str | None, offset: int, limit: int, kind: str | None = None, tag: str | None = None, tags: list[str] | None = None, match: str = "any") -> dict[str, Any]:
        path = f"/api/data/files/{quote(source_id, safe='')}/records" if source_id else "/api/data/records"
        parameters = {"kind": kind, "query": query, "date": date, "tag": tag, "tags": tags, "match": match, "offset": offset, "limit": limit}
        return self._get(path, parameters)

    def close(self) -> None:
        pass
