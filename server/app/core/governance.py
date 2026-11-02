from __future__ import annotations

import asyncio
import hashlib
import math
import os
import logging
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

import redis
from redis.exceptions import RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry
from starlette.responses import JSONResponse

from app.core.observability import current_request_id


QUOTAS = {"read": 240, "query": 60, "control": 20, "admin": 30, "login": 8, "ws": 20, "message": 120}
COUNT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], 60000) end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then redis.call('PEXPIRE', KEYS[1], 60000); ttl = 60000 end
return {count, ttl}
"""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry: int
    mode: str

    def headers(self):
        return {"X-RateLimit-Limit": str(self.limit), "X-RateLimit-Remaining": str(self.remaining), "X-RateLimit-Reset": str(self.retry), "X-RateLimit-Mode": self.mode}


class SharedLimiter:
    def __init__(self, client=None, namespace="marketlens:limits:v1", limits=None):
        self.client = client
        self.namespace = namespace
        self.limits = {**QUOTAS, **(limits or {})}
        self.local = OrderedDict()
        self.lock = Lock()

    def check(self, identity: str, category: str) -> Decision:
        key = self.namespace + ":" + hashlib.sha256((identity + ":" + category).encode()).hexdigest()
        limit = self.limits[category]
        mode = "local"
        if self.client is not None:
            try:
                count, ttl = self.client.eval(COUNT_SCRIPT, 1, key)
                return Decision(count <= limit, limit, max(0, limit - count), max(1, math.ceil(ttl / 1000)), "redis")
            except RedisError:
                if category not in {"read", "query"}:
                    raise
                limit = min(limit, 30)
                mode = "local-degraded"
        now = time.monotonic()
        with self.lock:
            count, until = self.local.pop(key, (0, now + 60))
            if until <= now:
                count, until = 0, now + 60
            count += 1
            self.local[key] = (count, until)
            while len(self.local) > 10000:
                self.local.popitem(last=False)
        return Decision(count <= limit, limit, max(0, limit - count), max(1, math.ceil(until - now)), mode)


def category_for(path, method):
    if path in {"/api/auth/login", "/api/auth/bootstrap"}:
        return "login"
    if method == "WEBSOCKET":
        return "ws"
    if path.startswith("/api/auth/users") or path.startswith("/api/auth/audit"):
        return "admin"
    if method not in {"GET", "HEAD", "OPTIONS"} and path != "/graphql":
        return "control"
    if path in {"/graphql", "/graphql/"} or path.startswith("/api/data/records") or (path.startswith("/api/data/files/") and path.endswith("/records")):
        return "query"
    return "read"


class GovernanceMiddleware:
    def __init__(self, app, limiter, service_name):
        self.app, self.limiter, self.service_name = app, limiter, service_name

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope.get("method", "WEBSOCKET")
        if method == "OPTIONS" or path in {"/api/health", "/api/health/ready", "/api/auth/status"}:
            return await self.app(scope, receive, send)
        principal = scope.get("state", {}).get("principal")
        identity = ("user:" + principal.username) if principal else ("client:" + str((scope.get("client") or ("unknown",))[0]))
        identity = self.service_name + ":" + identity
        category = category_for(path, method)
        if category == "login":
            identity += ":" + path
        decision = None
        status = 500
        accepted = False
        closed = False

        async def output(message):
            nonlocal status, accepted, closed
            if closed:
                return
            if message["type"] == "http.response.start":
                status = message["status"]
                names = {key.lower().encode() for key in decision.headers()} if decision else set()
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                if decision:
                    message["headers"] += [(k.lower().encode(), v.encode()) for k, v in decision.headers().items()]
            elif message["type"] == "websocket.accept":
                accepted = True
            elif message["type"] == "websocket.close":
                closed = True
            await send(message)

        async def reject(code, message):
            nonlocal status
            status = code
            if scope["type"] == "websocket":
                if not accepted:
                    await output({"type": "websocket.accept"})
                await output({"type": "websocket.close", "code": 4429 if code == 429 else 1013})
            else:
                headers = decision.headers() if decision else {}
                headers.update({"Retry-After": str(decision.retry if decision else 5), "Cache-Control": "no-store"})
                error = "rate_limited" if code == 429 else "rate_limit_unavailable"
                await JSONResponse({"detail": message, "error": {"code": error, "message": message, "request_id": current_request_id()}}, status_code=code, headers=headers)(scope, receive, output)

        async def limited_receive():
            event = await receive()
            if event["type"] == "websocket.receive":
                try:
                    incoming = await asyncio.to_thread(self.limiter.check, identity, "message")
                    if incoming.allowed:
                        return event
                    await reject(429, "订阅消息过于频繁")
                except RedisError:
                    await reject(503, "限流服务暂时不可用")
                return {"type": "websocket.disconnect", "code": 4429 if status == 429 else 1013}
            return event

        try:
            try:
                decision = await asyncio.to_thread(self.limiter.check, identity, category)
            except RedisError:
                return await reject(503, "限流服务暂时不可用，请稍后重试")
            if not decision.allowed:
                return await reject(429, "请求过于频繁，请稍后重试")
            if scope["type"] == "websocket":
                queue = asyncio.Queue(maxsize=16)

                async def pump():
                    while True:
                        event = await limited_receive()
                        await queue.put(event)
                        if event["type"] == "websocket.disconnect":
                            return

                reader = asyncio.create_task(pump())
                work = asyncio.create_task(self.app(scope, queue.get, output))
                try:
                    completed, _ = await asyncio.wait({reader, work}, return_when=asyncio.FIRST_COMPLETED)
                    for task in completed:
                        task.result()
                finally:
                    reader.cancel(); work.cancel()
                    await asyncio.gather(reader, work, return_exceptions=True)
            else:
                await self.app(scope, receive, output)
        finally:
            if self.service_name == "marketlens-api" and principal and not principal.service and method == "POST" and path.startswith("/api/replay/sessions"):
                from app.core.auth import auth_store
                parts = path.split("/")
                action = parts[-1] if parts[-1] in {"start", "pause", "resume", "speed", "restart"} else "create"
                target = parts[4][:40] if len(parts) > 4 else ""
                try:
                    await asyncio.to_thread(auth_store().record_event, principal.username, "replay_" + action, target, status)
                except (sqlite3.Error, OSError) as error:
                    logging.getLogger("marketlens.audit").error("audit_write_failed request_id=%s error_type=%s", current_request_id(), type(error).__name__)


def install_governance(app, config, service_name):
    mode = os.getenv("RATE_LIMIT_MODE", "local")
    if mode not in {"local", "redis"}:
        raise ValueError("RATE_LIMIT_MODE 必须为 local 或 redis")
    client = None
    if mode == "redis":
        settings = config.redis
        client = redis.Redis(host=settings["host"], port=int(settings["port"]), db=int(settings["db"]), password=settings["password"] or None, socket_connect_timeout=0.3, socket_timeout=0.3, retry=Retry(NoBackoff(), 0))
    limiter = SharedLimiter(client)
    app.state.governance = limiter
    app.state.governance_service_name = service_name
    app.add_middleware(GovernanceMiddleware, limiter=limiter, service_name=service_name)
    return limiter
