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
        return request.app.state.replays.create(payload.start_date, payload.end_date, payload.speed, payload.mode)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/replay/sessions/{session_id}")
def replay_detail(session_id: str, request: Request):
    return replay_session(request, session_id).snapshot()


@router.post("/api/replay/sessions/{session_id}/start")
async def start_replay(session_id: str, request: Request):
    try:
        return await replay_session(request, session_id).start()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/pause")
async def pause_replay(session_id: str, request: Request):
    try:
        return await replay_session(request, session_id).pause()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/resume")
async def resume_replay(session_id: str, request: Request):
    try:
        return await replay_session(request, session_id).resume()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/speed")
async def replay_speed(session_id: str, payload: ReplaySpeedRequest, request: Request):
    try:
        return await replay_session(request, session_id).set_speed(payload.speed)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/replay/sessions/{session_id}/restart")
async def restart_replay(session_id: str, request: Request):
    return await replay_session(request, session_id).restart()
