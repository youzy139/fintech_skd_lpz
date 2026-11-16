from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import AuthStore, auth_store, store_for
from app.main import create_app
from test_api import fake_service

PASSWORD = "test-only-workspace-password"


@pytest.fixture
def local_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_DATABASE_PATH", str(tmp_path / "auth.sqlite3"))
    store_for.cache_clear()
    service = fake_service()
    with TestClient(create_app(service, initialize=False)) as client:
        yield client, service, tmp_path / "auth.sqlite3"
    store_for.cache_clear()


def payload(**changes):
    value = {
        "search": "测试",
        "category": "权益",
        "watchlist_only": True,
        "watchlist": ["TEST"],
        "selected_asset": "TEST",
        "visible_range": 60,
    }
    value.update(changes)
    return value


def test_local_workspace_roundtrip_revision_and_asset_pruning(local_workspace):
    client, service, database = local_workspace
    initial = client.get("/api/research/workspace")
    assert initial.status_code == 200
    assert initial.json() == {
        "workspace_version": "market-workspace-v1", "search": "", "category": "all",
        "watchlist_only": False, "watchlist": [], "selected_asset": "TEST",
        "visible_range": 500, "revision": 0, "updated_at": None,
    }
    saved = client.put("/api/research/workspace", json=payload(watchlist=["TEST", "TEST"]))
    assert saved.status_code == 200, saved.text
    assert saved.json()["watchlist"] == ["TEST"]
    assert saved.json()["revision"] == 1
    assert isinstance(saved.json()["updated_at"], int)
    assert client.get("/api/research/workspace").json()["search"] == "测试"
    assert client.put("/api/research/workspace", json=payload(search="第二次")).json()["revision"] == 2
    reopened = AuthStore(database)
    assert reopened.research_workspace("local-dev")["payload"]["search"] == "第二次"
    service.assets = lambda: []
    pruned = client.get("/api/research/workspace").json()
    assert pruned["watchlist"] == []
    assert pruned["selected_asset"] == ""
    assert pruned["category"] == "all"
    assert client.put("/api/research/workspace", json=payload()).status_code == 422


@pytest.mark.parametrize("changes", [
    {"watchlist": ["MISSING"]},
    {"selected_asset": "MISSING"},
    {"visible_range": 30},
    {"category": ""},
    {"unexpected": True},
])
def test_workspace_rejects_invalid_or_unavailable_assets(local_workspace, changes):
    client, _, _ = local_workspace
    response = client.put("/api/research/workspace", json=payload(**changes))
    assert response.status_code == 422
    expected_code = "unprocessable_entity" if set(changes) <= {"watchlist", "selected_asset"} else "validation_error"
    assert response.json()["error"]["code"] == expected_code


def test_workspace_is_per_user_and_allows_observer_but_not_service_or_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_DATABASE_PATH", str(tmp_path / "auth.sqlite3"))
    store_for.cache_clear()
    store = auth_store()
    with store.connect() as database:
        setup_code = database.execute("SELECT value FROM auth_meta WHERE name='bootstrap'").fetchone()[0]
    with TestClient(create_app(fake_service(), initialize=False)) as client:
        origin = {"Origin": "http://localhost:5173"}
        assert client.post("/api/auth/bootstrap", json={"username": "admin", "password": PASSWORD, "setup_code": setup_code}, headers=origin).status_code == 200
        store.save_user("admin", "observer", PASSWORD, "observer", ["market"], True, create=True)
        store.save_user("admin", "other", PASSWORD, "observer", ["market"], True, create=True)
        store.save_user("admin", "catalog", PASSWORD, "observer", ["catalog"], True, create=True)
        observer = {"Authorization": "Bearer " + store.login("observer", PASSWORD)}
        other = {"Authorization": "Bearer " + store.login("other", PASSWORD)}
        catalog = {"Authorization": "Bearer " + store.login("catalog", PASSWORD)}
        service = {"Authorization": "Bearer " + store.service_token("backend")}
        assert client.put("/api/research/workspace", json=payload(), headers=observer).status_code == 200
        assert client.get("/api/research/workspace", headers=observer).json()["watchlist"] == ["TEST"]
        assert client.get("/api/research/workspace", headers=other).json()["watchlist"] == []
        assert client.get("/api/research/workspace").json()["watchlist"] == []
        assert client.get("/api/research/workspace", headers=catalog).status_code == 403
        assert client.put("/api/research/workspace", json=payload(), headers=catalog).status_code == 403
        assert client.get("/api/research/workspace", headers=service).status_code == 403
        assert client.put("/api/research/workspace", json=payload(), headers=service).status_code == 403
    store_for.cache_clear()


def test_workspace_read_and_write_enforce_current_asset_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_DATABASE_PATH", str(tmp_path / "auth.sqlite3"))
    store_for.cache_clear()
    store = auth_store()
    store.save_user("admin", "restricted", PASSWORD, "observer", ["market"], True, assets=["TEST"], sources=["*"], create=True)
    token = store.login("restricted", PASSWORD)
    headers = {"Authorization": "Bearer " + token}
    with TestClient(create_app(fake_service(), initialize=False)) as client:
        assert client.put("/api/research/workspace", json=payload(), headers=headers).status_code == 200
        store.save_user("admin", "restricted", None, "observer", ["market"], True, assets=["OTHER"], sources=["*"])
        fresh = {"Authorization": "Bearer " + store.login("restricted", PASSWORD)}
        pruned = client.get("/api/research/workspace", headers=fresh).json()
        assert pruned["watchlist"] == []
        assert pruned["selected_asset"] == ""
        denied = client.put("/api/research/workspace", json=payload(), headers=fresh)
        assert denied.status_code == 422
        assert denied.json()["detail"] == "工作区包含不存在或当前账号不可用的资产"
    store_for.cache_clear()
