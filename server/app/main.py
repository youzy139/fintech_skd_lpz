from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any

import strawberry
from graphql import GraphQLError
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON

from app.api.data import router as data_router
from app.api.auth import router as auth_router
from app.api.dependencies import replay_session
from app.api.market import router as market_router
from app.api.replay import router as replay_router
from app.api.system import router as system_router
from app.core.config import load_config
from app.core.auth import auth_enabled, install_auth, require_domain
from app.core.governance import install_governance
from app.core.observability import RequestMetrics, build_request_middleware, current_request_id, error_response, install_error_handlers
from app.core.serialization import json_compatible
from app.services.alert_proxy import forward_alert_request
from app.services.feature_proxy import forward_feature_request, forward_feature_websocket
from app.services.market import MarketService
from app.services.remote_alert import AlertServiceError, RemoteAlertClient
from app.services.remote_catalog import DataServiceError
from app.services.remote_feature import FeatureServiceError, RemoteFeatureService
from app.services.replay import ReplayManager
from app.services.replay_store import ReplayStore
from app.services.replay_capacity import ReplayCapacityError


@strawberry.type
class Query:
    @strawberry.field
    def assets(self, info: strawberry.Info) -> JSON:
        if auth_enabled():
            graphql_domain(info, "market")
        return info.context["service"].assets()

    @strawberry.field
    def latest_state(self, info: strawberry.Info) -> JSON:
        if auth_enabled():
            graphql_domain(info, "market")
        return info.context["service"].latest_state()

    @strawberry.field
    def source_summary(self, info: strawberry.Info) -> JSON:
        if auth_enabled():
            graphql_domain(info, "catalog")
        return info.context["service"].source_summary()


def graphql_domain(info, domain):
    try:
        require_domain(info.context["principal"], domain)
    except HTTPException as error:
        raise GraphQLError(error.detail, extensions={"code": "forbidden", "request_id": current_request_id()}) from None


class SafeSchema(strawberry.Schema):
    def process_errors(self, errors, execution_context=None):
        logging.getLogger("marketlens.graphql").warning("GraphQL rejected request_id=%s error_count=%s", current_request_id(), len(errors))


schema = SafeSchema(query=Query)


def create_app(service: Any | None = None, initialize: bool = True, replay_store: ReplayStore | None = None, title: str = "金融市场状态监控平台", service_name: str = "marketlens-api") -> FastAPI:
    config = load_config()
    remote_mode = service is None and bool(config.feature_service["url"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.alert_service = None
        if service is not None:
            app.state.service = service
        elif remote_mode:
            app.state.service = RemoteFeatureService(config)
            if config.alert_service["url"]:
                app.state.alert_service = RemoteAlertClient(config.alert_service["url"], config.alert_service["timeout_seconds"])
        else:
            app.state.service = MarketService(config)
        if initialize and not remote_mode:
            await asyncio.to_thread(app.state.service.initialize)
        if remote_mode:
            app.state.replays = None
        else:
            store = replay_store or (ReplayStore(":memory:") if not initialize else None)
            app.state.replays = ReplayManager(app.state.service, config, store, app.state.replay_leases)
            app.state.service.replay_manager = app.state.replays
        retention_worker = None
        if service_name == "marketlens-api" and auth_enabled() and config.minio.get("enabled", False):
            from app.services.audit_archive import audit_archive

            async def retain_audit():
                interval = max(60, int(os.getenv("AUDIT_ARCHIVE_INTERVAL_SECONDS", "3600")))
                while True:
                    await asyncio.sleep(interval)
                    try:
                        await asyncio.to_thread(audit_archive().archive_expired)
                    except Exception as error:
                        logging.getLogger("marketlens.audit").error("audit_archive_failed error_type=%s", type(error).__name__)

            retention_worker = asyncio.create_task(retain_audit())
        try:
            yield
        finally:
            if retention_worker is not None:
                retention_worker.cancel()
                await asyncio.gather(retention_worker, return_exceptions=True)
            if app.state.replays is not None:
                await app.state.replays.close()
            if service is None:
                app.state.service.close()
                if app.state.alert_service is not None:
                    app.state.alert_service.close()

    app = FastAPI(title=title, version="0.3.3", lifespan=lifespan)
    install_governance(app, config, service_name)
    install_auth(app, config.cors_origins)
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins, allow_methods=["*"], allow_headers=["*"])
    app.state.metrics = RequestMetrics()
    requests: dict[str, deque[float]] = defaultdict(deque)
    app.middleware("http")(build_request_middleware(app.state.metrics, requests, service_name=service_name))
    install_error_handlers(app)

    @app.exception_handler(ReplayCapacityError)
    async def replay_capacity_error(_: Request, error: ReplayCapacityError):
        return error_response(error.status_code, error.code, error.detail, error.detail, error.headers)
    if service_name == "marketlens-api":
        app.include_router(auth_router)

    @app.exception_handler(DataServiceError)
    async def data_service_unavailable(_: Request, __: DataServiceError):
        return error_response(503, "data_service_unavailable", "数据服务暂时不可用", "数据服务暂时不可用", {"Retry-After": "5"})

    @app.exception_handler(FeatureServiceError)
    async def feature_service_unavailable(_: Request, __: FeatureServiceError):
        return error_response(503, "feature_service_unavailable", "特征与状态服务暂时不可用", "特征与状态服务暂时不可用", {"Retry-After": "5"})

    @app.exception_handler(AlertServiceError)
    async def alert_service_unavailable(_: Request, __: AlertServiceError):
        return error_response(503, "alert_service_unavailable", "预警服务暂时不可用", "预警服务暂时不可用", {"Retry-After": "5"})

    app.include_router(system_router)
    app.include_router(data_router)
    if remote_mode:
        if config.alert_service["url"]:
            @app.get("/api/alerts", include_in_schema=False)
            async def alert_proxy(request: Request):
                return await forward_alert_request(request, config.alert_service["url"], float(config.alert_service["timeout_seconds"]))

            @app.api_route("/api/alerts/{path:path}", methods=["GET"], include_in_schema=False)
            @app.api_route("/api/alert-rules", methods=["GET", "PUT"], include_in_schema=False)
            @app.api_route("/api/alert-rules/{path:path}", methods=["GET", "POST"], include_in_schema=False)
            async def alert_management_proxy(request: Request):
                return await forward_alert_request(request, config.alert_service["url"], float(config.alert_service["timeout_seconds"]))

        @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
        async def feature_proxy(request: Request):
            return await forward_feature_request(request, config.feature_service["url"], float(config.feature_service["timeout_seconds"]))

        def openapi_schema():
            if app.openapi_schema is None:
                app.openapi_schema = app.state.service.feature.get("/openapi.json")
                local = get_openapi(title=app.title, version=app.version, routes=app.routes)
                app.openapi_schema["paths"].update({path: definition for path, definition in local["paths"].items() if path.startswith("/api/auth/")})
                app.openapi_schema.setdefault("components", {}).setdefault("schemas", {}).update(local.get("components", {}).get("schemas", {}))
            return app.openapi_schema
        app.openapi = openapi_schema

        @app.websocket("/ws/{path:path}")
        async def feature_websocket_proxy(websocket: WebSocket):
            app.state.metrics.websocket_connected()
            try:
                await forward_feature_websocket(websocket, config.feature_service["url"], float(config.feature_service["timeout_seconds"]))
            finally:
                app.state.metrics.websocket_disconnected()
    else:
        app.include_router(market_router)
        app.include_router(replay_router)

        @app.websocket("/ws/replay/{session_id}")
        async def replay_updates(websocket: WebSocket, session_id: str):
            await websocket.accept()
            try:
                session = replay_session(websocket, session_id)
            except HTTPException:
                await websocket.close(code=4404)
                return
            queue = asyncio.Queue(maxsize=100)
            session.subscribers.add(queue)
            app.state.metrics.websocket_connected()
            try:
                await websocket.send_json(json_compatible({"type": "replay_snapshot", "session": session.snapshot()}))
                while True:
                    await websocket.send_json(json_compatible(await queue.get()))
            finally:
                session.subscribers.discard(queue)
                app.state.metrics.websocket_disconnected()

        @app.websocket("/ws/replay")
        async def replay(websocket: WebSocket, start_index: int = 0, max_messages: int = 20):
            await websocket.accept()
            app.state.metrics.websocket_connected()
            try:
                service = websocket.app.state.service
                end = min(len(service.states), max(0, start_index) + max(1, min(max_messages, 100)))
                for index in range(max(0, start_index), end):
                    state = service.states[index]
                    await websocket.send_json(json_compatible({"type": "market_state", "event_time": state["date"], "replay_time": asyncio.get_running_loop().time(), "state": state, "alerts": [item for item in service.alerts if item["date"] == state["date"]]}))
                    await asyncio.sleep(config.replay["interval_ms"] / 1000)
                await websocket.send_json({"type": "replay_complete", "sent": end - max(0, start_index)})
                await websocket.close()
            finally:
                app.state.metrics.websocket_disconnected()

    def graphql_context(request: Request) -> dict[str, Any]:
        return {"service": request.app.state.service, "principal": getattr(request.state, "principal", None)}

    graphql = GraphQLRouter(schema, context_getter=graphql_context)
    app.include_router(graphql, prefix="/graphql")
    return app


app = create_app()
