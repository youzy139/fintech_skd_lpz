from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from starlette.websockets import WebSocketDisconnect

from app.core.auth import AuthStore
from app.core.config import load_config
from app.core.governance import GovernanceMiddleware, SharedLimiter, category_for, install_governance
from app.core.leases import ConnectionLeases
from app.core.resilience import CircuitBreaker
from test_auth import bootstrap, secured, create_user, bearer, ORIGIN


class Counter:
    def __init__(self):
        from threading import Lock
        self.lock = Lock()
        self.values = {}

    def eval(self, script, number, key):
        with self.lock:
            self.values[key] = self.values.get(key, 0) + 1
            return self.values[key], 60000


class BrokenRedis:
    def __init__(self):
        self.calls = 0

    def eval(self, *args):
        self.calls += 1
        raise ConnectionError('offline')


def test_shared_atomic_budget_and_separate_users_categories():
    assert category_for('/api/data/files/source-id/records', 'GET') == 'query'
    counter = Counter()
    instances = [SharedLimiter(counter, limits={'read': 10}) for _ in range(2)]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda i: instances[i % 2].check('user', 'read'), range(30)))
    assert sum(item.allowed for item in results) == 10
    assert instances[1].check('another-user', 'read').allowed
    assert instances[0].check('user', 'control').allowed
    assert all('user' not in key for key in counter.values)


def test_redis_outage_read_budget_and_write_closed():
    limiter = SharedLimiter(BrokenRedis())
    results = [limiter.check('reader', 'read') for _ in range(31)]
    assert sum(item.allowed for item in results) == 30
    assert results[-1].mode == 'local-degraded'
    for category in ('control', 'admin', 'login', 'ws', 'message'):
        with pytest.raises(ConnectionError):
            limiter.check('user', category)


def test_open_circuit_short_circuits_limiter_and_leases_then_recovers():
    now = [0.0]
    broken = BrokenRedis()
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=5, clock=lambda: now[0])
    limiter = SharedLimiter(broken, breaker=breaker)
    leases = ConnectionLeases(broken, breaker=breaker)
    limiter.check('reader', 'read')
    limiter.check('reader', 'read')
    assert breaker.snapshot()['state'] == 'open'
    calls = broken.calls
    for _ in range(5):
        assert limiter.check('reader', 'read').mode == 'local-degraded'
        with pytest.raises(ConnectionError):
            limiter.check('writer', 'control')
        with pytest.raises(ConnectionError):
            leases.acquire('writer')
    assert broken.calls == calls
    now[0] = 6
    limiter.client = Counter()
    assert limiter.check('reader', 'read').mode == 'redis'
    assert breaker.snapshot()['state'] == 'closed'


def test_http_quota_headers_and_health_exemption():
    app = FastAPI()
    limiter = SharedLimiter(limits={'read': 1})
    app.add_middleware(GovernanceMiddleware, limiter=limiter, service_name='test')
    app.get('/api/assets')(lambda: {'ok': True})
    app.get('/api/health')(lambda: {'ok': True})
    with TestClient(app) as client:
        first = client.get('/api/assets')
        assert first.headers['x-ratelimit-remaining'] == '0'
        limited = client.get('/api/assets')
        assert limited.status_code == 429 and limited.headers['retry-after'] == '60'
        assert limited.json()['error']['code'] == 'rate_limited'
        assert client.get('/api/health').status_code == 200
        limiter.client = BrokenRedis()
        assert client.post('/api/auth/login').status_code == 503


def test_websocket_message_and_connection_limits():
    app = FastAPI()
    limiter = SharedLimiter(limits={'ws': 1, 'message': 1})
    app.add_middleware(GovernanceMiddleware, limiter=limiter, service_name='test')

    @app.websocket('/ws/replay/test')
    async def socket(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                await ws.send_text(await ws.receive_text())
        except WebSocketDisconnect:
            pass

    with TestClient(app) as client:
        with client.websocket_connect('/ws/replay/test') as ws:
            ws.send_text('first'); assert ws.receive_text() == 'first'
            ws.send_text('second')
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_text()
            assert error.value.code == 4429
        with client.websocket_connect('/ws/replay/test') as ws:
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_text()
            assert error.value.code == 4429


def test_default_websocket_capacity_exceeds_100_and_remains_configurable(monkeypatch):
    monkeypatch.delenv("WS_MAX_CONNECTIONS_TOTAL", raising=False)
    app = FastAPI()
    install_governance(app, load_config(), "test-capacity")
    assert app.state.connection_leases.total == 128
    monkeypatch.setenv("WS_MAX_CONNECTIONS_TOTAL", "100")
    limited = FastAPI()
    install_governance(limited, load_config(), "test-capacity")
    assert limited.state.connection_leases.total == 100


def test_audit_migration_preserves_history_and_key(tmp_path):
    path = tmp_path / 'auth.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE auth_audit (id INTEGER PRIMARY KEY, occurred INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL)')
        db.execute("INSERT INTO auth_audit VALUES(1,1,'legacy','login','legacy')")
    store = AuthStore(path)
    key = store.key
    assert store.audit_records()['items'][0]['actor'] == 'legacy'
    assert AuthStore(path).key == key


def test_audit_permission_cursor_filters_and_safe_metadata(secured):
    client, store, code = secured
    bootstrap(client, code)
    for _ in range(4):
        store.record_event('admin', 'replay_pause', 'session1', 200)
    first = client.get('/api/auth/audit?limit=2&actor=admin&action=replay_pause').json()
    assert len(first['items']) == 2 and first['next_before']
    second = client.get(f"/api/auth/audit?limit=2&before={first['next_before']}&action=replay_pause").json()
    assert {item['id'] for item in first['items']}.isdisjoint(item['id'] for item in second['items'])
    assert second['next_before'] is None
    assert client.get('/api/auth/audit?limit=101').status_code == 422
    assert client.get('/api/auth/audit', headers=bearer(create_user(store))).status_code == 403
    response = client.post('/api/replay/sessions', headers={**ORIGIN, 'X-Request-ID': 'audit-trace'}, json={'start_date': '2024-01-01', 'end_date': '2024-01-02'})
    assert response.status_code == 201
    latest = client.get('/api/auth/audit?action=replay_create').json()['items'][0]
    assert latest['request_id'] == 'audit-trace' and latest['status'] == 201
    assert set(latest) == {'id', 'occurred', 'actor', 'action', 'target', 'request_id', 'status'}
