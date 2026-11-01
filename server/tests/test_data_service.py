from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.core.observability import request_id_context
from app.data_service import create_data_app
from app.services.remote_catalog import DataServiceError, RemoteCatalogClient


def fake_catalog_service():
    return SimpleNamespace(
        storage_mode="local",
        data_version=lambda: "version-1",
        source_summary=lambda: {"total_files": 1, "imported_files": 1, "total_records": 2, "errors": 0, "groups": []},
        source_overview=lambda kind: {"kind": kind, "files": 1, "records": 2, "trend": []},
        source_tags=lambda kind: [{"tag": "人工智能", "records": 2}],
        source_files=lambda kind, query, offset, limit: {"total": 1, "items": [{"id": "来源一"}]},
        source_records=lambda source_id, query, date, offset, limit, kind=None, tag=None, tags=None, match="any": {"total": 1, "offset": offset, "limit": limit, "items": [{"source_id": source_id, "tags": tags, "match": match}]},
    )


def test_data_service_exposes_only_catalog_and_system_contracts():
    with TestClient(create_data_app(fake_catalog_service())) as http:
        assert http.get("/api/health").json()["service"] == "data"
        assert http.get("/api/health/ready").json()["checks"]["catalog"]["records"] == 2
        assert http.get("/api/data/version").json() == {"data_version": "version-1"}
        assert http.get("/api/data/overview?kind=social").json()["records"] == 2
        response = http.get("/api/data/files/来源一/records?tags=人工智能&tags=半导体&match=all")
        assert response.status_code == 200
        assert response.json()["items"][0]["source_id"] == "来源一"
        assert response.json()["items"][0]["tags"] == ["人工智能", "半导体"]
        assert response.json()["items"][0]["match"] == "all"
        assert http.get("/api/assets").status_code == 404
        assert http.get("/api/system/metrics").json()["scope"] == "process"


def test_data_service_readiness_fails_when_catalog_is_unavailable():
    service = fake_catalog_service()

    def unavailable():
        raise RuntimeError("private database detail")
    service.source_summary = unavailable
    with TestClient(create_data_app(service)) as http:
        response = http.get("/api/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["catalog"]["status"] == "unavailable"
        assert "private database detail" not in response.text


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode("utf-8")


def test_remote_catalog_forwards_filters_and_request_id():
    calls = []

    def open_response(request, timeout):
        calls.append((request, timeout))
        if urlsplit(request.full_url).path == "/api/data/version":
            return FakeResponse({"data_version": "version-2"})
        return FakeResponse({"total": 0, "items": []})

    client = RemoteCatalogClient("http://data-service:8000/", 2.5, open_response)
    token = request_id_context.set("trace.data-1")
    try:
        assert client.data_version() == "version-2"
        result = client.list_records("来源/一", "通胀", "2024-01-02", 20, 40, "news", tags=["宏观", "利率"], match="all")
    finally:
        request_id_context.reset(token)
    assert result["total"] == 0
    request, timeout = calls[-1]
    parsed = urlsplit(request.full_url)
    assert parsed.path == "/api/data/files/%E6%9D%A5%E6%BA%90%2F%E4%B8%80/records"
    query = parse_qs(parsed.query)
    assert query["tags"] == ["宏观", "利率"]
    assert query["match"] == ["all"]
    assert query["offset"] == ["20"]
    assert request.headers["X-request-id"] == "trace.data-1"
    assert timeout == 2.5


def test_remote_catalog_hides_transport_and_response_details():
    def unavailable(request, timeout):
        raise URLError("private host detail")
    client = RemoteCatalogClient("http://data-service:8000", opener=unavailable)
    with pytest.raises(DataServiceError, match="暂时不可用"):
        client.summary()
    invalid = RemoteCatalogClient("http://data-service:8000", opener=lambda request, timeout: FakeResponse(b"not-json"))
    with pytest.raises(DataServiceError):
        invalid.summary()
    with pytest.raises(ValueError, match="HTTP"):
        RemoteCatalogClient("file:///tmp/catalog")
    with pytest.raises(ValueError, match="超时"):
        RemoteCatalogClient("http://data-service:8000", 0)
