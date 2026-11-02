from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import current_service

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health(request: Request):
    service = current_service(request)
    return {"status": "ok", "version": "0.3.3", **service.health_details()}


@router.get("/api/health/ready")
def ready(request: Request):
    service = current_service(request)
    checks = {}
    try:
        checks["market"] = service.market_readiness()
    except Exception:
        checks["market"] = {"status": "unavailable"}
    try:
        summary = service.source_summary()
        checks["catalog"] = {"status": "ok", "records": summary["total_records"]}
    except Exception:
        checks["catalog"] = {"status": "unavailable"}
    available = checks["market"]["status"] == "ok" and checks["catalog"]["status"] == "ok"
    return JSONResponse(status_code=200 if available else 503, content={"status": "ok" if available else "unavailable", "checks": checks})


@router.get("/api/system/metrics")
async def metrics(request: Request):
    return {**request.app.state.metrics.snapshot(), **current_service(request).replay_metrics()}
