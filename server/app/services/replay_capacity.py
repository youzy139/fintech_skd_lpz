from __future__ import annotations

import asyncio
import time
from functools import wraps

from fastapi import HTTPException
from redis.exceptions import RedisError


class ReplayCapacityError(HTTPException):
    def __init__(self, unavailable=False):
        self.code = "replay_capacity_unavailable" if unavailable else "replay_capacity_exceeded"
        detail = "回放资源治理暂时不可用，请稍后重试" if unavailable else "回放计算已达并发上限，或此会话正在其他实例运行；请暂停其他回放后重试"
        super().__init__(503 if unavailable else 429, detail, headers={"Retry-After": "5"})


class ReplayLeaseLost(RuntimeError):
    pass


def serialized_control(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with self.control_lock:
            temporary = method.__name__ in {"pause", "set_speed"} and self.compute_lease is None
            if temporary:
                await self.reserve()
            try:
                if method.__name__ in {"pause", "set_speed"}:
                    self.require_lease()
                return await method(self, *args, **kwargs)
            except BaseException:
                if self.compute_lease and (not self.task or self.task.done()):
                    await self.release()
                raise
            finally:
                if temporary:
                    await self.release()
    return wrapped


async def lease_call(pool, method, *args):
    return await asyncio.wait_for(asyncio.to_thread(method, *args), min(1.0, pool.ttl / 3))


async def acquire(pool, session_id):
    deadline = time.monotonic() + pool.ttl
    try:
        lease = await lease_call(pool, pool.acquire, session_id)
    except (RedisError, TimeoutError):
        raise ReplayCapacityError(unavailable=True) from None
    if lease is None:
        raise ReplayCapacityError()
    return lease, deadline
