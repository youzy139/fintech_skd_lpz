from __future__ import annotations

import json
import logging
import math
import re
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

request_id_context: ContextVar[str] = ContextVar("request_id", default="")
request_logger = logging.getLogger("marketlens.requests")
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def current_request_id() -> str:
    return request_id_context.get()


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def error_response(status_code: int, code: str, detail: Any, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": jsonable_encoder(detail), "error": {"code": code, "message": message, "request_id": current_request_id()}},
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException):
        codes = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "unprocessable_entity", 429: "rate_limited"}
        message = error.detail if isinstance(error.detail, str) else "请求失败"
        return error_response(error.status_code, codes.get(error.status_code, "http_error"), error.detail, message, error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        return error_response(422, "validation_error", error.errors(), "请求参数不符合接口契约")


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[position], 3)


class RequestMetrics:
    def __init__(self, capacity: int = 512):
        self.capacity = capacity
        self.started = monotonic()
        self.started_at = datetime.now(timezone.utc)
        self.lock = RLock()
        self.routes: dict[tuple[str, str], deque[float]] = {}
        self.route_counts: dict[tuple[str, str], int] = {}
        self.request_count = 0
        self.error_count = 0
        self.server_error_count = 0
        self.websocket_connections = 0
        self.websocket_connections_total = 0

    def record(self, method: str, route: str, status: int, duration_ms: float) -> None:
        key = (method, route)
        with self.lock:
            if key not in self.routes:
                self.routes[key] = deque(maxlen=self.capacity)
            self.routes[key].append(duration_ms)
            self.route_counts[key] = self.route_counts.get(key, 0) + 1
            self.request_count += 1
            self.error_count += int(status >= 400)
            self.server_error_count += int(status >= 500)

    def websocket_connected(self) -> None:
        with self.lock:
            self.websocket_connections += 1
            self.websocket_connections_total += 1

    def websocket_disconnected(self) -> None:
        with self.lock:
            self.websocket_connections = max(0, self.websocket_connections - 1)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            routes = []
            for key, durations in self.routes.items():
                method, route = key
                values = list(durations)
                routes.append({
                    "method": method,
                    "route": route,
                    "requests": self.route_counts[key],
                    "sample_size": len(values),
                    "last_ms": round(values[-1], 3),
                    "p50_ms": percentile(values, 0.5),
                    "p95_ms": percentile(values, 0.95),
                    "p99_ms": percentile(values, 0.99),
                    "max_ms": round(max(values), 3),
                })
            return {
                "scope": "process",
                "started_at": self.started_at.isoformat(),
                "uptime_seconds": round(monotonic() - self.started, 3),
                "request_count": self.request_count,
                "error_count": self.error_count,
                "server_error_count": self.server_error_count,
                "websocket_connections": self.websocket_connections,
                "websocket_connections_total": self.websocket_connections_total,
                "routes": sorted(routes, key=lambda item: (item["route"], item["method"])),
            }


def build_request_middleware(metrics: RequestMetrics, requests: dict[str, deque[float]]):
    async def observe(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else uuid4().hex
        token = request_id_context.set(request_id)
        started = monotonic()
        status = 500
        try:
            now = monotonic()
            client = request.client.host if request.client else "local"
            recent = requests[client]
            while recent and now - recent[0] > 60:
                recent.popleft()
            if len(recent) >= 240:
                retry_after = max(1, math.ceil(60 - (now - recent[0])))
                response = error_response(429, "rate_limited", "请求过于频繁，请稍后重试", "请求过于频繁，请稍后重试", {"Retry-After": str(retry_after)})
            else:
                recent.append(now)
                try:
                    response = await call_next(request)
                except Exception as error:
                    request_logger.error(
                        json.dumps({"event": "http_request_failed", "request_id": request_id, "method": request.method, "error_type": type(error).__name__}, ensure_ascii=False),
                        exc_info=(type(error), error, error.__traceback__),
                    )
                    response = error_response(500, "internal_error", "服务器内部错误", "服务器内部错误")
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = (monotonic() - started) * 1000
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            metrics.record(request.method, route_path, status, duration_ms)
            fields = {
                "request_id": request_id,
                "method": request.method,
                "route": route_path,
                "status": status,
                "duration_ms": round(duration_ms, 3),
                "service": "marketlens-api",
            }
            session_id = request.path_params.get("session_id")
            if session_id:
                fields["session_id"] = session_id
            log_event(request_logger, "http_request", **fields)
            request_id_context.reset(token)

    return observe
