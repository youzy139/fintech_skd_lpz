from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.governance import GovernanceMiddleware, SharedLimiter
from app.core.leases import ConnectionLeases
from test_governance import BrokenRedis


def test_local_atomic_user_and_total_capacity():
    leases = ConnectionLeases(per_user=2, total=3)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: leases.acquire("alice"), range(20)))
    held = [item for item in results if item]
    assert len(held) == 2
    other = leases.acquire("bob")
    assert other and leases.acquire("charlie") is None
    leases.release(held[0])
    assert leases.acquire("charlie")
    assert not leases.renew(held[0])
    assert all("alice" not in item[0] for item in leases.local.values())


def test_expiry_does_not_resurrect_stale_owner():
    leases = ConnectionLeases(per_user=1, total=1, ttl=0.3)
    original = leases.acquire("alice")
    time.sleep(0.35)
    replacement = leases.acquire("alice")
    assert replacement
    assert not leases.renew(original)
    leases.release(original)
    assert leases.renew(replacement)
    assert leases.acquire("bob") is None


def socket_app(leases):
    app = FastAPI()
    app.add_middleware(GovernanceMiddleware, limiter=SharedLimiter(), service_name="test", leases=leases)

    @app.websocket("/ws/replay/test")
    async def socket(ws: WebSocket):
        await ws.accept()
        await ws.send_text("ready")
        # The real subscription is push-only; its receive pump must detect disconnect.
        import asyncio
        await asyncio.Event().wait()

    return app


def test_subscription_release_and_excess_reason():
    leases = ConnectionLeases(per_user=1)
    with TestClient(socket_app(leases)) as client:
        with client.websocket_connect("/ws/replay/test") as first:
            assert first.receive_text() == "ready"
            with client.websocket_connect("/ws/replay/test") as extra:
                with pytest.raises(WebSocketDisconnect) as error:
                    extra.receive_text()
                assert error.value.code == 4429
                assert error.value.reason == "connection_limit"
        # TestClient closing the socket waits for application cleanup.
        with client.websocket_connect("/ws/replay/test") as replacement:
            assert replacement.receive_text() == "ready"
    assert not leases.local


@pytest.mark.parametrize("fault", ["redis", "lost_lease"])
def test_idle_subscription_closes_on_renewal_failure(fault):
    leases = ConnectionLeases(ttl=0.3)
    with TestClient(socket_app(leases)) as client:
        with client.websocket_connect("/ws/replay/test") as ws:
            assert ws.receive_text() == "ready"
            if fault == "redis":
                leases.client = BrokenRedis()
            else:
                leases.local.clear()
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_text()
            assert error.value.code == 1013
            assert error.value.reason == ("connection_lease_unavailable" if fault == "redis" else "connection_lease_expired")


def test_renewal_retains_idle_connection_past_ttl():
    leases = ConnectionLeases(per_user=1, ttl=0.3)
    with TestClient(socket_app(leases)) as client:
        with client.websocket_connect("/ws/replay/test") as ws:
            assert ws.receive_text() == "ready"
            time.sleep(0.7)
            assert leases.acquire("another")
            assert len(leases.local) == 2
