from __future__ import annotations

import asyncio
from types import SimpleNamespace

import anyio.to_thread
import pytest

from app.core.config import configure_thread_pool_from_env, prewarm_worker_threads


def test_thread_pool_is_bounded_and_opt_in(monkeypatch):
    limiter = SimpleNamespace(total_tokens=40)
    monkeypatch.setattr(anyio.to_thread, "current_default_thread_limiter", lambda: limiter)
    monkeypatch.delenv("SERVER_THREAD_POOL_SIZE", raising=False)
    configure_thread_pool_from_env()
    assert limiter.total_tokens == 40
    monkeypatch.setenv("SERVER_THREAD_POOL_SIZE", "128")
    configure_thread_pool_from_env()
    assert limiter.total_tokens == 128


@pytest.mark.parametrize("value", ["0", "257", "not-a-number"])
def test_thread_pool_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("SERVER_THREAD_POOL_SIZE", value)
    with pytest.raises(ValueError, match="1～256"):
        configure_thread_pool_from_env()


def test_worker_prewarm_happens_before_requests_and_respects_smaller_limit(monkeypatch):
    calls = []

    async def fake_to_thread(function, *args):
        calls.append(function)
        function(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setenv("SERVER_THREAD_POOL_SIZE", "3")
    asyncio.run(prewarm_worker_threads())
    assert len(calls) == 3
