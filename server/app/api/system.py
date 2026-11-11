from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import current_service
from app.core.config import load_config
from app.services.dependencies import DependencyMonitor

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health(request: Request):
    service = current_service(request)
    return {"status": "ok", "version": "0.3.4", **service.health_details()}


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
    alert_service = getattr(request.app.state, "alert_service", None)
    if alert_service is not None:
        try:
            checks["alerts"] = alert_service.readiness()
        except Exception:
            checks["alerts"] = {"status": "unavailable"}
    available = all(check["status"] == "ok" for check in checks.values())
    return JSONResponse(status_code=200 if available else 503, content={"status": "ok" if available else "unavailable", "checks": checks})


@router.get("/api/system/metrics")
async def metrics(request: Request):
    return {**request.app.state.metrics.snapshot(), **current_service(request).replay_metrics()}


@router.get("/api/system/dependencies")
async def dependencies(request: Request):
    report = await DependencyMonitor(load_config()).snapshot()
    report["governance"] = request.app.state.governance.status()
    cache_stats = getattr(getattr(current_service(request), "catalog", None), "cache_stats", None)
    if cache_stats is not None:
        report["catalog_cache"] = cache_stats
    return report
