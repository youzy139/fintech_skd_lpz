from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import current_service

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health(request: Request):
    service = current_service(request)
    return {"status": "ok", "version": "0.3.3", "storage_mode": getattr(service, "storage_mode", "local"), "assets": len(service.series), "states": len(service.states)}


@router.get("/api/health/ready")
def ready(request: Request):
    service = current_service(request)
    checks = {}
    market_ready = bool(service.series and service.states)
    checks["market"] = {"status": "ok" if market_ready else "unavailable", "assets": len(service.series), "states": len(service.states)}
    try:
        summary = service.source_summary()
        checks["catalog"] = {"status": "ok", "records": summary["total_records"]}
    except Exception:
        checks["catalog"] = {"status": "unavailable"}
    available = market_ready and checks["catalog"]["status"] == "ok"
    return JSONResponse(status_code=200 if available else 503, content={"status": "ok" if available else "unavailable", "checks": checks})


@router.get("/api/system/metrics")
async def metrics(request: Request):
    snapshot = request.app.state.metrics.snapshot()
    sessions = list(request.app.state.replays.sessions.values())
    return {
        **snapshot,
        "replay_sessions": len(sessions),
        "active_replays": sum(session.clock.status in {"running", "paused"} for session in sessions),
    }
