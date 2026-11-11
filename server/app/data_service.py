from __future__ import annotations

from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.data import router as data_router
from app.core.config import load_config
from app.core.auth import install_auth
from app.core.governance import install_governance
from app.core.observability import RequestMetrics, build_request_middleware, install_error_handlers
from app.services.data_catalog import DataCatalogService


def create_data_app(service: DataCatalogService | None = None) -> FastAPI:
    config = load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or DataCatalogService(config)
        try:
            yield
        finally:
            if service is None:
                app.state.service.close()

    app = FastAPI(title="MarketLens 数据服务", version="0.3.4", lifespan=lifespan)
    install_governance(app, config, "marketlens-data")
    install_auth(app, config.cors_origins)
    app.state.metrics = RequestMetrics()
    requests: dict[str, deque[float]] = defaultdict(deque)
    app.middleware("http")(build_request_middleware(app.state.metrics, requests, service_name="marketlens-data"))
    install_error_handlers(app)
    app.include_router(data_router)

    @app.get("/api/health", tags=["system"])
    def health(request: Request):
        report = {"status": "ok", "service": "data", "version": app.version, "storage_mode": request.app.state.service.storage_mode}
        catalog = getattr(request.app.state.service, "catalog", None)
        cache_stats = getattr(catalog, "cache_stats", None)
        if cache_stats is not None:
            report["catalog_cache"] = cache_stats
        return report

    @app.get("/api/health/ready", tags=["system"])
    def ready(request: Request):
        try:
            summary = request.app.state.service.source_summary()
            check = {"status": "ok", "records": summary["total_records"]}
        except Exception:
            check = {"status": "unavailable"}
        return JSONResponse(status_code=200 if check["status"] == "ok" else 503, content={"status": check["status"], "checks": {"catalog": check}})

    @app.get("/api/system/metrics", tags=["system"])
    def metrics(request: Request):
        return request.app.state.metrics.snapshot()

    return app


app = create_data_app()
