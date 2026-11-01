from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.contracts import ReplayCreateRequest, ReplaySpeedRequest
from app.api.dependencies import replay_session

router = APIRouter(tags=["replay"])


@router.get("/api/replay/calendar")
def replay_calendar(request: Request):
    return request.app.state.replays.calendar()


@router.get("/api/kafka/status")
def kafka_status(request: Request):
    return request.app.state.replays.kafka_status()


@router.get("/api/flink/status")
def flink_status(request: Request):
    return request.app.state.replays.flink_status()


@router.get("/api/replay/sessions/current")
def current_replay(request: Request):
    return request.app.state.replays.current()


@router.post("/api/replay/sessions", status_code=201)
def create_replay(payload: ReplayCreateRequest, request: Request):
    try:
        return request.app.state.replays.create(payload.start_date, payload.end_date, payload.speed, payload.mode, request.headers.get("idempotency-key"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/replay/sessions/{session_id}")
def replay_detail(session_id: str, request: Request):
    return replay_session(request, session_id).snapshot()


@router.get("/api/replay/sessions/{session_id}/results")
def replay_results(session_id: str, request: Request, after: int = 0, limit: int = 100):
    if after < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="after 必须非负，limit 必须在 1 到 100 之间")
    return request.app.state.replays.results(session_id, after, limit)


@router.post("/api/replay/sessions/{session_id}/start")
async def start_replay(session_id: str, request: Request):
    try:
        return await replay_session(request, session_id).start(request.headers.get("idempotency-key"))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/pause")
async def pause_replay(session_id: str, request: Request):
    try:
        return await replay_session(request, session_id).pause(request.headers.get("idempotency-key"))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/resume")
async def resume_replay(session_id: str, request: Request):
    try:
        return await replay_session(request, session_id).resume(request.headers.get("idempotency-key"))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/speed")
async def replay_speed(session_id: str, payload: ReplaySpeedRequest, request: Request):
    try:
        return await replay_session(request, session_id).set_speed(payload.speed, request.headers.get("idempotency-key"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/restart")
async def restart_replay(session_id: str, request: Request):
    try:
        return await replay_session(request, session_id).restart(request.headers.get("idempotency-key"))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
