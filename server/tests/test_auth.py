from __future__ import annotations

import asyncio
import time

import jwt
import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.auth import AuthStore, COOKIE, auth_store, outgoing_auth_headers, store_for
from app.data_service import create_data_app
from app.main import create_app
from test_api import fake_service

ORIGIN = {"Origin": "http://localhost:5173"}
PASSWORD = "test-only-password-123"


@pytest.fixture
def secured(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_DATABASE_PATH", str(tmp_path / "auth.sqlite3"))
    store = auth_store()
    code = (tmp_path / "auth-bootstrap.txt").read_text()
    with TestClient(create_app(fake_service(), initialize=False)) as client:
        yield client, store, code
    store_for.cache_clear()


def bootstrap(client, code):
    response = client.post("/api/auth/bootstrap", json={"username": "admin", "password": PASSWORD, "setup_code": code}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    return response


def create_user(store, username="observer", role="observer", domains=("market", "catalog")):
    store.save_user("admin", username, PASSWORD, role, domains, True, create=True)
    return store.login(username, PASSWORD)


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_setup_login_cookie_logout_and_single_use_bootstrap(secured):
    client, store, code = secured
    assert client.get("/api/auth/status").json() == {"enabled": True, "setup_required": True}
    missing = client.get("/api/assets", headers={"X-Request-ID": "trace.auth"})
    assert missing.status_code == 401
    assert missing.json()["error"] == {"code": "unauthenticated", "message": "请先登录", "request_id": "trace.auth"}
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert client.get("/api/health/ready").status_code == 200
    invalid = client.post("/api/auth/bootstrap", json={"username": "admin", "password": PASSWORD, "setup_code": "incorrect"}, headers=ORIGIN)
    assert invalid.status_code == 403
    response = bootstrap(client, code)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert not store.path.with_name("auth-bootstrap.txt").exists()
    token = client.cookies.get(COOKIE)
    assert client.get("/api/auth/me").json()["role"] == "admin"
    assert client.post("/api/auth/bootstrap", json={"username": "other", "password": PASSWORD, "setup_code": code}, headers=ORIGIN).status_code == 403
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 200
    assert client.get("/api/assets", headers=bearer(token)).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "bad"}, headers=ORIGIN).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=ORIGIN).status_code == 200


def test_csrf_and_login_throttle(secured):
    client, store, code = secured
    bootstrap(client, code)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers={"Origin": "https://evil.example"}).status_code == 403
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}, headers=ORIGIN).status_code == 401
    limited = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=ORIGIN)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_roles_data_scopes_and_graphql_aliases(secured):
    client, store, code = secured
    bootstrap(client, code)
    observer = bearer(create_user(store))
    assert client.get("/api/assets", headers=observer).status_code == 200
    assert client.get("/api/data/records", headers=observer).status_code == 200
    assert client.post("/api/replay/sessions", json={"start_date": "2024-01-01", "end_date": "2024-01-02"}, headers=observer).status_code == 403
    assert client.get("/api/auth/users", headers=observer).status_code == 403
    assert client.get("/api/system/metrics", headers=observer).status_code == 403
    market = bearer(create_user(store, "market-user", domains=("market",)))
    assert client.get("/api/data/records", headers=market).status_code == 403
    assert client.get("/api/home/summary", headers=market).status_code == 403
    assert client.get("/api/replay/calendar", headers=market).status_code == 403
    result = client.post("/graphql", json={"query": "query Q { allowed: assets ...Private } fragment Private on Query { hidden: sourceSummary }"}, headers=market)
    assert "errors" in result.json()
    assert result.json()["errors"][0]["message"] == "没有访问此数据范围的权限"
    catalog = bearer(create_user(store, "catalog-user", domains=("catalog",)))
    assert client.get("/api/assets", headers=catalog).status_code == 403
    assert client.get("/api/data/records", headers=catalog).status_code == 200
    assert client.post("/graphql", json={"query": "{ sourceSummary }"}, headers=catalog).json()["data"]["sourceSummary"]["total_records"] == 2
    analyst = bearer(create_user(store, "analyst", "analyst"))
    assert client.post("/api/replay/sessions", json={"start_date": "2024-01-01", "end_date": "2024-01-02"}, headers=analyst).status_code == 201


def test_jwt_verification_revocation_and_admin_invariants(secured):
    client, store, code = secured
    bootstrap(client, code)
    token = create_user(store)
    claims = store.claims(token)
    variants = [{**claims, "exp": int(time.time()) - 1}, {**claims, "aud": "other"}, {**claims, "iss": "other"}, {key: value for key, value in claims.items() if key != "jti"}]
    for payload in variants:
        signed = jwt.encode(payload, store.key, algorithm="HS256")
        assert client.get("/api/assets", headers=bearer(signed)).status_code == 401
    assert client.get("/api/assets", headers=bearer(token + "tampered")).status_code == 401
    assert client.put("/api/auth/users/admin", json={"role": "observer", "domains": ["market"], "enabled": True}, headers=ORIGIN).status_code == 409
    updated = client.put("/api/auth/users/observer", json={"role": "analyst", "domains": ["market", "catalog"], "enabled": True}, headers=ORIGIN)
    assert updated.status_code == 200
    assert client.get("/api/assets", headers=bearer(token)).status_code == 401
    fresh = store.login("observer", PASSWORD)
    store.save_user("admin", "observer", None, "analyst", ["market", "catalog"], False)
    assert client.get("/api/assets", headers=bearer(fresh)).status_code == 401


def test_service_identity_and_direct_service_access(secured):
    client, store, code = secured
    bootstrap(client, code)
    assert client.get("/api/internal/alert-states").status_code == 403
    service = bearer(store.service_token("backend"))
    assert client.get("/api/internal/alert-states", headers=service).status_code == 403
    assert client.post("/api/auth/users", json={}, headers=service).status_code == 403
    assert "Authorization" in outgoing_auth_headers()
    with TestClient(create_data_app(fake_service())) as direct:
        assert direct.get("/api/data/records").status_code == 401
        assert direct.get("/api/data/records", headers=service).status_code == 200
        token = create_user(store, "only-market", domains=("market",))
        assert direct.get("/api/data/records", headers=bearer(token)).status_code == 403


def test_user_administration_persistence_and_no_secret_disclosure(secured):
    client, store, code = secured
    bootstrap(client, code)
    payload = {"username": "new-reader", "password": PASSWORD, "role": "observer", "domains": ["catalog"]}
    assert client.post("/api/auth/users", json=payload, headers=ORIGIN).status_code == 201
    assert client.post("/api/auth/users", json=payload, headers=ORIGIN).status_code == 409
    listed = client.get("/api/auth/users")
    assert "password" not in listed.text and PASSWORD not in listed.text
    token = store.login("new-reader", PASSWORD)
    reopened = AuthStore(store.path)
    assert reopened.verify(token).domains == frozenset({"catalog"})
    updated = client.put("/api/auth/users/new-reader", json={"role": "analyst", "domains": ["market", "catalog"], "enabled": True, "password": "different-test-password"}, headers=ORIGIN)
    assert updated.status_code == 200
    assert client.get("/api/data/records", headers=bearer(token)).status_code == 401
    assert store.login("new-reader", "different-test-password")
    with store.connect() as db:
        audit = json_text = str([dict(row) for row in db.execute("SELECT * FROM auth_audit")])
        stored_password = db.execute("SELECT password FROM auth_users WHERE username='admin'").fetchone()[0]
    assert PASSWORD not in audit and token not in json_text and code not in audit
    assert stored_password != PASSWORD


def test_websocket_auth_origin_logout_and_permission_revocation(secured):
    client, store, code = secured
    bootstrap(client, code)
    token = create_user(store)
    client.cookies.clear()
    with client.websocket_connect("/ws/replay/missing") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401
    with client.websocket_connect("/ws/replay/missing", headers={"Cookie": COOKIE + "=" + token, "Origin": "https://evil.example"}) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4403


    headers = bearer(token)
    created = client.post("/api/replay/sessions", json={"start_date": "2024-01-01", "end_date": "2024-01-02"}, headers=bearer(create_user(store, "operator", "analyst"))).json()
    with client.websocket_connect("/ws/replay/" + created["id"], headers=headers) as ws:
        assert ws.receive_json()["type"] == "replay_snapshot"
        store.logout(token)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401
    limited = create_user(store, "no-catalog", domains=("market",))
    with client.websocket_connect("/ws/replay/missing", headers=bearer(limited)) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4403


def test_revocation_close_code_precedes_proxy_cleanup(secured):
    client, store, code = secured
    bootstrap(client, code)
    token = create_user(store)

    @client.app.websocket("/ws/cleanup")
    async def cleanup(websocket: WebSocket):
        await websocket.accept()
        try:
            await websocket.send_json({"connected": True})
            await asyncio.Event().wait()
        finally:
            await websocket.close(code=1000)

    with client.websocket_connect("/ws/cleanup", headers=bearer(token)) as ws:
        assert ws.receive_json()["connected"]
        store.logout(token)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401
