from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from app.api.contracts import RuleRequest
from app.core.config import load_config
from app.core.auth import auth_enabled, auth_store, install_auth
from app.core.governance import install_governance
from app.core.observability import RequestMetrics, build_request_middleware, error_response, install_error_handlers
from app.services.alert import AlertService
from app.services.remote_feature import FeatureServiceError


def rule_actor(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    return principal.username if principal else "local-dev"


def audit_rule(request: Request, action: str, version: str) -> None:
    if auth_enabled():
        auth_store().record_event(rule_actor(request), action, version, 200)


def create_alert_app(service: AlertService | None = None, initialize: bool = True) -> FastAPI:
    config = load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or AlertService(config)
        if initialize:
            await asyncio.to_thread(app.state.service.initialize)
        try:
            yield
        finally:
            if service is None:
                app.state.service.close()

    app = FastAPI(title="MarketLens 预警服务", version="0.3.3", lifespan=lifespan)
    install_governance(app, config, "marketlens-alert")
    install_auth(app, config.cors_origins)
    app.state.metrics = RequestMetrics()
    requests: dict[str, deque[float]] = defaultdict(deque)
    app.middleware("http")(build_request_middleware(app.state.metrics, requests, service_name="marketlens-alert"))
    install_error_handlers(app)

    @app.exception_handler(FeatureServiceError)
    async def feature_service_unavailable(_: Request, __: FeatureServiceError):
        return error_response(503, "feature_service_unavailable", "特征与状态服务暂时不可用", "特征与状态服务暂时不可用", {"Retry-After": "5"})

    @app.get("/api/alerts", tags=["alerts"])
    def alerts(request: Request, limit: int = Query(100, ge=1, le=1000)):
        return request.app.state.service.list_alerts(limit)

    @app.get("/api/alerts/{rule}/{event_date}", tags=["alerts"])
    def evidence(rule: str, event_date: str, request: Request):
        try:
            return request.app.state.service.alert_evidence(rule, event_date)
        except KeyError:
            raise HTTPException(404, "未找到该预警或对应证据") from None

    @app.get("/api/alert-rules", tags=["alerts"])
    def rules(request: Request):
        return request.app.state.service.alert_rules()

    @app.put("/api/alert-rules", tags=["alerts"])
    def update_rules(payload: RuleRequest, request: Request):
        try:
            result = request.app.state.service.update_alert_rules(payload.model_dump(), rule_actor(request))
            audit_rule(request, "rule_update", result["version"])
            return result
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.post("/api/alert-rules/{version}/activate", tags=["alerts"])
    def activate_rule(version: str, request: Request):
        try:
            result = request.app.state.service.activate_alert_rule(version, rule_actor(request))
            audit_rule(request, "rule_activate", result["version"])
            return result
        except KeyError:
            raise HTTPException(404, "规则版本不存在") from None

    @app.get("/api/health", tags=["system"])
    def health(request: Request):
        return {"status": "ok", "service": "alert", "version": app.version, **request.app.state.service.health_details()}

    @app.get("/api/health/ready", tags=["system"])
    def ready(request: Request):
        check = request.app.state.service.readiness()
        return JSONResponse(status_code=200 if check["status"] == "ok" else 503, content={"status": check["status"], "checks": {"alerts": check}})

    @app.get("/api/system/metrics", tags=["system"])
    def metrics(request: Request):
        return request.app.state.metrics.snapshot()

    return app


app = create_alert_app()
