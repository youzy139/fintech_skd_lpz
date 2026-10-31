from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket

from app.services.market import MarketService


def current_service(request: Request | WebSocket) -> MarketService:
    return request.app.state.service


def replay_session(request: Request | WebSocket, session_id: str):
    try:
        return request.app.state.replays.get(session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
