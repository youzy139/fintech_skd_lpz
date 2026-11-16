from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query as QueryParam, Request

from app.api.contracts import ResearchWorkspaceRequest, RuleRequest
from app.api.dependencies import current_service
from app.core.auth import auth_enabled, auth_store, has_full_scope, require_scope

router = APIRouter(tags=["market"])


def allowed_assets(request: Request) -> list[dict]:
    principal = getattr(request.state, "principal", None)
    values = current_service(request).assets()
    if principal is None or "*" in principal.assets:
        return values
    return [item for item in values if item["code"] in principal.assets]


def workspace_response(record: dict | None, assets: list[dict]) -> dict:
    payload = record["payload"] if record and isinstance(record.get("payload"), dict) else {}
    codes = [item["code"] for item in assets]
    allowed = set(codes)
    watchlist = payload.get("watchlist", [])
    if not isinstance(watchlist, list):
        watchlist = []
    selected = payload.get("selected_asset", "")
    if not isinstance(selected, str) or selected not in allowed:
        selected = "SPX.GI" if "SPX.GI" in allowed else (codes[0] if codes else "")
    categories = {item.get("category") for item in assets}
    category = payload.get("category", "all")
    if not isinstance(category, str) or (category != "all" and category not in categories):
        category = "all"
    search = payload.get("search", "")
    visible_range = payload.get("visible_range", 500)
    return {
        "workspace_version": "market-workspace-v1",
        "search": search if isinstance(search, str) else "",
        "category": category,
        "watchlist_only": payload.get("watchlist_only") is True,
        "watchlist": [code for code in dict.fromkeys(watchlist) if isinstance(code, str) and code in allowed],
        "selected_asset": selected,
        "visible_range": visible_range if visible_range in {60, 250, 500} else 500,
        "revision": record["revision"] if record else 0,
        "updated_at": record["updated_at"] if record else None,
    }


def workspace_username(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    return principal.username if principal else "local-dev"


@router.get("/api/research/workspace")
def research_workspace(request: Request):
    assets = allowed_assets(request)
    return workspace_response(auth_store().research_workspace(workspace_username(request)), assets)


@router.put("/api/research/workspace")
def save_research_workspace(payload: ResearchWorkspaceRequest, request: Request):
    assets = allowed_assets(request)
    allowed = {item["code"] for item in assets}
    requested = set(payload.watchlist) | ({payload.selected_asset} if payload.selected_asset else set())
    if not requested <= allowed:
        raise HTTPException(422, "工作区包含不存在或当前账号不可用的资产")
    canonical = payload.model_dump()
    canonical["watchlist"] = list(dict.fromkeys(canonical["watchlist"]))
    record = auth_store().save_research_workspace(workspace_username(request), canonical)
    return workspace_response(record, assets)


@router.get("/api/assets")
async def assets(request: Request):
    return allowed_assets(request)


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


@router.get("/api/regimes/evaluation/stability")
def regime_stability(request: Request):
    try:
        return current_service(request).stability_evaluation()
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


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


@router.get("/api/research/cases/latest")
def latest_research_case(request: Request):
    try:
        principal = getattr(request.state, "principal", None)
        if has_full_scope(principal, "source"):
            return current_service(request).research_case()
        return current_service(request).research_case(principal.sources)
    except KeyError:
        raise HTTPException(404, "当前没有可用于研究案例的历史预警") from None


@router.get("/api/data/quality")
def quality(request: Request):
    if not has_full_scope(getattr(request.state, "principal", None), "source"):
        raise HTTPException(403, "来源范围受限账号不可查看全局质量摘要")
    return current_service(request).quality


@router.get("/api/home/summary")
def home_summary(request: Request):
    return current_service(request).home_summary()
