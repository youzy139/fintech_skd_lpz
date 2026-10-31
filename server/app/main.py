from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import strawberry
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON

from app.api.data import router as data_router
from app.api.dependencies import replay_session
from app.api.market import router as market_router
from app.api.replay import router as replay_router
from app.api.system import router as system_router
from app.core.config import load_config
from app.core.observability import RequestMetrics, build_request_middleware, install_error_handlers
from app.services.market import MarketService
from app.services.replay import ReplayManager


@strawberry.type
class Query:
    @strawberry.field
    def assets(self, info: strawberry.Info) -> JSON:
        return info.context["service"].assets()

    @strawberry.field
    def latest_state(self, info: strawberry.Info) -> JSON:
        return info.context["service"].latest_state()

    @strawberry.field
    def source_summary(self, info: strawberry.Info) -> JSON:
        return info.context["service"].source_summary()


schema = strawberry.Schema(query=Query)


def create_app(service: MarketService | None = None, initialize: bool = True) -> FastAPI:
    config = load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or MarketService(config)
        if initialize:
            await asyncio.to_thread(app.state.service.initialize)
        app.state.replays = ReplayManager(app.state.service, config)
        try:
            yield
        finally:
            await app.state.replays.close()
            if service is None:
                app.state.service.close()

    app = FastAPI(title="金融市场状态监控平台", version="0.3.3", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins, allow_methods=["*"], allow_headers=["*"])
    app.state.metrics = RequestMetrics()
    requests: dict[str, deque[float]] = defaultdict(deque)
    app.middleware("http")(build_request_middleware(app.state.metrics, requests))
    install_error_handlers(app)
    for router in (system_router, market_router, data_router, replay_router):
        app.include_router(router)

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
            await websocket.send_json({"type": "replay_snapshot", "session": session.snapshot()})
            while True:
                await websocket.send_json(await queue.get())
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
                await websocket.send_json({"type": "market_state", "event_time": state["date"], "replay_time": asyncio.get_running_loop().time(), "state": state, "alerts": [item for item in service.alerts if item["date"] == state["date"]]})
                await asyncio.sleep(config.replay["interval_ms"] / 1000)
            await websocket.send_json({"type": "replay_complete", "sent": end - max(0, start_index)})
            await websocket.close()
        finally:
            app.state.metrics.websocket_disconnected()

    def graphql_context(request: Request) -> dict[str, MarketService]:
        return {"service": request.app.state.service}

    graphql = GraphQLRouter(schema, context_getter=graphql_context)
    app.include_router(graphql, prefix="/graphql")
    return app


app = create_app()
