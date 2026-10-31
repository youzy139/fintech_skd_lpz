from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query as QueryParam, Request

from app.api.dependencies import current_service

router = APIRouter(tags=["market"])


@router.get("/api/assets")
def assets(request: Request):
    return current_service(request).assets()


@router.get("/api/assets/{code}/series")
def asset_series(code: str, request: Request, limit: int = QueryParam(500, ge=1, le=10000)):
    try:
        return current_service(request).asset_series(code, limit)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="资产不存在") from error


@router.get("/api/regimes/latest")
def latest_regime(request: Request):
    return current_service(request).latest_state()


@router.get("/api/regimes")
def regimes(request: Request, start: str | None = None, end: str | None = None, limit: int = QueryParam(2000, ge=1, le=10000)):
    states = current_service(request).states
    filtered = [item for item in states if (start is None or item["date"] >= start) and (end is None or item["date"] <= end)]
    return filtered[-limit:]


@router.get("/api/features/latest")
def latest_features(request: Request):
    state = current_service(request).latest_state()
    return {"date": state["date"], "features": state["features"], "contributions": state["contributions"], "model_version": state["model_version"]}


@router.get("/api/alerts")
def alerts(request: Request, limit: int = QueryParam(100, ge=1, le=1000)):
    return list(reversed(current_service(request).alerts[-limit:]))


@router.get("/api/data/quality")
def quality(request: Request):
    return current_service(request).quality


@router.get("/api/home/summary")
def home_summary(request: Request):
    return current_service(request).home_summary()
