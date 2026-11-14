from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query as QueryParam, Request

from app.api.contracts import RuleRequest
from app.api.dependencies import current_service
from app.core.auth import auth_enabled, auth_store, has_full_scope, require_scope

router = APIRouter(tags=["market"])


@router.get("/api/assets")
async def assets(request: Request):
    principal = getattr(request.state, "principal", None)
    values = current_service(request).assets()
    if principal is None or "*" in principal.assets:
        return values
    return [item for item in values if item["code"] in principal.assets]


@router.get("/api/assets/{code}/series")
def asset_series(code: str, request: Request, limit: int = QueryParam(500, ge=1, le=10000)):
    require_scope(getattr(request.state, "principal", None), "asset", code)
    try:
        return current_service(request).asset_series(code, limit)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="资产不存在") from error


@router.get("/api/regimes/latest")
async def latest_regime(request: Request):
    return current_service(request).latest_state()


@router.get("/api/regimes")
def regimes(request: Request, start: str | None = None, end: str | None = None, limit: int = QueryParam(2000, ge=1, le=10000)):
    states = current_service(request).states
    filtered = [item for item in states if (start is None or item["date"] >= start) and (end is None or item["date"] <= end)]
    return filtered[-limit:]


@router.get("/api/internal/alert-states", include_in_schema=False)
def alert_states(request: Request):
    return current_service(request).alert_states()


@router.get("/api/features/metadata")
def feature_metadata(request: Request):
    return current_service(request).feature_metadata()


@router.get("/api/features/latest")
def latest_features(request: Request):
    return current_service(request).latest_features()


@router.get("/api/alerts")
async def alerts(request: Request, limit: int = QueryParam(100, ge=1, le=1000)):
    return list(reversed(current_service(request).alerts[-limit:]))


@router.get("/api/alerts/{rule}/{event_date}")
def alert_evidence(rule: str, event_date: str, request: Request):
    try:
        principal = getattr(request.state, "principal", None)
        if has_full_scope(principal, "source"):
            return current_service(request).alert_evidence(rule, event_date)
        return current_service(request).alert_evidence(rule, event_date, principal.sources)
    except KeyError:
        raise HTTPException(404, "未找到该预警或对应证据") from None


@router.get("/api/alert-rules")
def alert_rules(request: Request):
    return current_service(request).alert_rules()


@router.put("/api/alert-rules")
def update_alert_rules(payload: RuleRequest, request: Request):
    principal = getattr(request.state, "principal", None)
    actor = principal.username if principal else "local-dev"
    result = current_service(request).update_alert_rules(payload.model_dump(), actor)
    if auth_enabled():
        auth_store().record_event(actor, "rule_update", result["version"], 200)
    return result


@router.post("/api/alert-rules/{version}/activate")
def activate_alert_rule(version: str, request: Request):
    principal = getattr(request.state, "principal", None)
    actor = principal.username if principal else "local-dev"
    try:
        result = current_service(request).activate_alert_rule(version, actor)
        if auth_enabled():
            auth_store().record_event(actor, "rule_activate", result["version"], 200)
        return result
    except KeyError:
        raise HTTPException(404, "规则版本不存在") from None


@router.get("/api/data/quality")
def quality(request: Request):
    if not has_full_scope(getattr(request.state, "principal", None), "source"):
        raise HTTPException(403, "来源范围受限账号不可查看全局质量摘要")
    return current_service(request).quality


@router.get("/api/home/summary")
def home_summary(request: Request):
    return current_service(request).home_summary()
