from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date
from time import monotonic
from typing import Literal

import strawberry
from fastapi import FastAPI, HTTPException, Query as QueryParam, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON

from app.core.config import load_config
from app.services.market import MarketService
from app.services.replay import ReplayManager


class ReplayCreateRequest(BaseModel):
    start_date: date
    end_date: date
    speed: float = 1.0
    mode: Literal["local", "kafka"] = "local"


class ReplaySpeedRequest(BaseModel):
    speed: float


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

    app = FastAPI(title="金融市场状态监控平台", version="0.3.1", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins, allow_methods=["*"], allow_headers=["*"])
    requests: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        now = monotonic()
        client = request.client.host if request.client else "local"
        recent = requests[client]
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= 240:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后重试"})
        recent.append(now)
        return await call_next(request)

    def current_service(request: Request) -> MarketService:
        return request.app.state.service

    @app.get("/api/health")
    def health(request: Request):
        service = current_service(request)
        return {"status": "ok", "version": "0.3.1", "assets": len(service.series), "states": len(service.states)}

    @app.get("/api/assets")
    def assets(request: Request):
        return current_service(request).assets()

    @app.get("/api/assets/{code}/series")
    def asset_series(code: str, request: Request, limit: int = QueryParam(500, ge=1, le=10000)):
        try:
            return current_service(request).asset_series(code, limit)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="资产不存在") from error

    @app.get("/api/regimes/latest")
    def latest_regime(request: Request):
        return current_service(request).latest_state()

    @app.get("/api/regimes")
    def regimes(request: Request, start: str | None = None, end: str | None = None, limit: int = QueryParam(2000, ge=1, le=10000)):
        states = current_service(request).states
        filtered = [item for item in states if (start is None or item["date"] >= start) and (end is None or item["date"] <= end)]
        return filtered[-limit:]

    @app.get("/api/features/latest")
    def latest_features(request: Request):
        state = current_service(request).latest_state()
        return {"date": state["date"], "features": state["features"], "contributions": state["contributions"], "model_version": state["model_version"]}

    @app.get("/api/alerts")
    def alerts(request: Request, limit: int = QueryParam(100, ge=1, le=1000)):
        return list(reversed(current_service(request).alerts[-limit:]))

    @app.get("/api/data/quality")
    def quality(request: Request):
        return current_service(request).quality

    @app.get("/api/home/summary")
    def home_summary(request: Request):
        return current_service(request).home_summary()

    @app.get("/api/data/summary")
    def source_summary(request: Request):
        return current_service(request).source_summary()

    @app.get("/api/data/overview")
    def source_overview(request: Request, kind: str | None = None):
        return current_service(request).source_overview(kind)

    @app.get("/api/data/tags")
    def source_tags(request: Request, kind: str | None = None):
        return current_service(request).source_tags(kind)

    @app.get("/api/data/records")
    def records(request: Request, kind: str | None = None, query: str | None = None, date: str | None = None, tag: str | None = None, tags: list[str] = QueryParam(default=[], max_length=5), match: str = QueryParam("any", pattern="^(any|all)$"), offset: int = QueryParam(0, ge=0), limit: int = QueryParam(20, ge=1, le=100)):
        return current_service(request).source_records(None, query, date, offset, limit, kind, tag, tags, match)

    @app.get("/api/data/files")
    def source_files(request: Request, kind: str | None = None, query: str | None = None, offset: int = QueryParam(0, ge=0), limit: int = QueryParam(50, ge=1, le=100)):
        return current_service(request).source_files(kind, query, offset, limit)

    @app.get("/api/data/files/{source_id}/records")
    def source_records(source_id: str, request: Request, query: str | None = None, date: str | None = None, tag: str | None = None, tags: list[str] = QueryParam(default=[], max_length=5), match: str = QueryParam("any", pattern="^(any|all)$"), offset: int = QueryParam(0, ge=0), limit: int = QueryParam(20, ge=1, le=100)):
        return current_service(request).source_records(source_id, query, date, offset, limit, tag=tag, tags=tags, match=match)

    def replay_session(request: Request, session_id: str):
        try:
            return request.app.state.replays.get(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/replay/calendar")
    def replay_calendar(request: Request):
        return request.app.state.replays.calendar()

    @app.get("/api/kafka/status")
    def kafka_status(request: Request):
        return request.app.state.replays.kafka_status()

    @app.get("/api/replay/sessions/current")
    def current_replay(request: Request):
        return request.app.state.replays.current()

    @app.post("/api/replay/sessions", status_code=201)
    def create_replay(payload: ReplayCreateRequest, request: Request):
        try:
            return request.app.state.replays.create(payload.start_date, payload.end_date, payload.speed, payload.mode)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/replay/sessions/{session_id}")
    def replay_detail(session_id: str, request: Request):
        return replay_session(request, session_id).snapshot()

    @app.post("/api/replay/sessions/{session_id}/start")
    async def start_replay(session_id: str, request: Request):
        try:
            return await replay_session(request, session_id).start()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/replay/sessions/{session_id}/pause")
    async def pause_replay(session_id: str, request: Request):
        try:
            return await replay_session(request, session_id).pause()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/replay/sessions/{session_id}/resume")
    async def resume_replay(session_id: str, request: Request):
        try:
            return await replay_session(request, session_id).resume()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/replay/sessions/{session_id}/speed")
    async def replay_speed(session_id: str, payload: ReplaySpeedRequest, request: Request):
        try:
            return await replay_session(request, session_id).set_speed(payload.speed)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/replay/sessions/{session_id}/restart")
    async def restart_replay(session_id: str, request: Request):
        return await replay_session(request, session_id).restart()

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
        try:
            await websocket.send_json({"type": "replay_snapshot", "session": session.snapshot()})
            while True:
                await websocket.send_json(await queue.get())
        finally:
            session.subscribers.discard(queue)

    @app.websocket("/ws/replay")
    async def replay(websocket: WebSocket, start_index: int = 0, max_messages: int = 20):
        await websocket.accept()
        service = websocket.app.state.service
        end = min(len(service.states), max(0, start_index) + max(1, min(max_messages, 100)))
        for index in range(max(0, start_index), end):
            state = service.states[index]
            await websocket.send_json({"type": "market_state", "event_time": state["date"], "replay_time": asyncio.get_running_loop().time(), "state": state, "alerts": [item for item in service.alerts if item["date"] == state["date"]]})
            await asyncio.sleep(config.replay["interval_ms"] / 1000)
        await websocket.send_json({"type": "replay_complete", "sent": end - max(0, start_index)})
        await websocket.close()

    def graphql_context(request: Request) -> dict[str, MarketService]:
        return {"service": request.app.state.service}

    graphql = GraphQLRouter(schema, context_getter=graphql_context)
    app.include_router(graphql, prefix="/graphql")
    return app


app = create_app()
