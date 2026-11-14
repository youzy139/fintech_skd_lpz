from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from redis.exceptions import ConnectionError, RedisError

from app.core.resilience import CircuitBreaker


LEASE_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local token, action, ttl = ARGV[1], ARGV[2], tonumber(ARGV[3])
for i = 1, 2 do redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now) end
if action == 'release' then
    for i = 1, 2 do redis.call('ZREM', KEYS[i], token) end
    return 1
end
if action == 'acquire' then
    if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[4]) or
       redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[5]) then return 0 end
else
    if not redis.call('ZSCORE', KEYS[1], token) or not redis.call('ZSCORE', KEYS[2], token) then
        for i = 1, 2 do redis.call('ZREM', KEYS[i], token) end
        return 0
    end
end
for i = 1, 2 do
    redis.call('ZADD', KEYS[i], now + ttl, token)
    redis.call('PEXPIRE', KEYS[i], ttl)
end
return 1
"""


@dataclass(frozen=True)
class Lease:
    identity: str
    token: str


class ConnectionLeases:
    def __init__(self, client=None, namespace="marketlens:connections:v1", per_user=3, total=128, ttl=30.0, breaker: CircuitBreaker | None = None):
        if per_user < 1 or total < 1 or ttl < 0.3:
            raise ValueError("连接并发额度必须为正，租约期限至少 0.3 秒")
        self.client, self.namespace = client, namespace
        self.per_user, self.total, self.ttl = per_user, total, ttl
        self.breaker = breaker or CircuitBreaker()
        self.lock = Lock()
        self.local: dict[str, tuple[str, float]] = {}

    def _change(self, lease: Lease, action: str) -> bool:
        if self.client is not None:
            if not self.breaker.before_call():
                raise ConnectionError("Redis circuit breaker is open")
            keys = [self.namespace + ":all", self.namespace + ":user:" + lease.identity]
            try:
                changed = bool(self.client.eval(LEASE_SCRIPT, 2, *keys, lease.token, action, int(self.ttl * 1000), self.total, self.per_user))
                self.breaker.after_call(True)
                return changed
            except RedisError:
                self.breaker.after_call(False)
                raise
        with self.lock:
            now = time.monotonic()
            self.local = {token: item for token, item in self.local.items() if item[1] > now}
            if action == "release":
                self.local.pop(lease.token, None)
                return True
            if action == "acquire":
                if len(self.local) >= self.total or sum(item[0] == lease.identity for item in self.local.values()) >= self.per_user:
                    return False
            elif lease.token not in self.local:
                return False
            self.local[lease.token] = (lease.identity, now + self.ttl)
            return True

    def acquire(self, identity: str) -> Lease | None:
        lease = Lease(hashlib.sha256(identity.encode()).hexdigest(), uuid4().hex)
        return lease if self._change(lease, "acquire") else None

    def renew(self, lease: Lease) -> bool:
        return self._change(lease, "renew")

    def release(self, lease: Lease) -> None:
        self._change(lease, "release")
