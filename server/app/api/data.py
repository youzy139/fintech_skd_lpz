from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query as QueryParam, Request

from app.api.dependencies import current_service
from app.core.auth import has_full_scope, require_scope
from app.services.remote_catalog import DataServiceError

router = APIRouter(tags=["data"])


@router.get("/api/data/version")
def data_version(request: Request):
    return {"data_version": current_service(request).data_version()}


@router.get("/api/data/summary")
def source_summary(request: Request):
    if not has_full_scope(getattr(request.state, "principal", None), "source"):
        raise HTTPException(403, "来源范围受限账号不可查看全局汇总信息")
    return current_service(request).source_summary()


@router.get("/api/data/overview")
def source_overview(request: Request, kind: str | None = None):
    if not has_full_scope(getattr(request.state, "principal", None), "source"):
        raise HTTPException(403, "来源范围受限账号不可查看全局汇总信息")
    return current_service(request).source_overview(kind)


@router.get("/api/data/tags")
def source_tags(request: Request, kind: str | None = None):
    if not has_full_scope(getattr(request.state, "principal", None), "source"):
        raise HTTPException(403, "来源范围受限账号不可查看全局标签统计")
    return current_service(request).source_tags(kind)


@router.get("/api/data/governance")
def source_governance(request: Request, kind: Literal["asset", "calendar", "commodity", "indicator", "news", "publication", "research", "social"] | None = None):
    if not has_full_scope(getattr(request.state, "principal", None), "source"):
        raise HTTPException(403, "来源范围受限账号不可查看全局治理报告")
    try:
        return current_service(request).source_governance(kind)
    except DataServiceError as error:
        raise HTTPException(503, "来源治理报告暂时不可用，请重试", headers={"Retry-After": "5"}) from error


@router.get("/api/data/records")
def records(request: Request, kind: str | None = None, query: str | None = None, date: str | None = None, tag: str | None = None, tags: list[str] = QueryParam(default=[], max_length=5), match: str = QueryParam("any", pattern="^(any|all)$"), offset: int = QueryParam(0, ge=0), limit: int = QueryParam(20, ge=1, le=100)):
    if not has_full_scope(getattr(request.state, "principal", None), "source"):
        raise HTTPException(403, "来源范围受限账号请先选择已授权来源查询记录")
    return current_service(request).source_records(None, query, date, offset, limit, kind, tag, tags, match)


@router.get("/api/data/files")
def source_files(request: Request, kind: str | None = None, query: str | None = None, offset: int = QueryParam(0, ge=0), limit: int = QueryParam(50, ge=1, le=100)):
    principal = getattr(request.state, "principal", None)
    service = current_service(request)
    if has_full_scope(principal, "source"):
        return service.source_files(kind, query, offset, limit)
    allowed = principal.sources if principal else frozenset()
    matches = []
    cursor = 0
    while True:
        page = service.source_files(kind, query, cursor, 100)
        matches.extend(item for item in page["items"] if item["id"] in allowed)
        cursor += len(page["items"])
        if cursor >= page["total"] or not page["items"]:
            break
    return {"total": len(matches), "offset": offset, "limit": limit, "items": matches[offset:offset + limit]}


@router.get("/api/data/files/{source_id}/records")
def source_records(source_id: str, request: Request, query: str | None = None, date: str | None = None, kind: str | None = None, tag: str | None = None, tags: list[str] = QueryParam(default=[], max_length=5), match: str = QueryParam("any", pattern="^(any|all)$"), offset: int = QueryParam(0, ge=0), limit: int = QueryParam(20, ge=1, le=100)):
    require_scope(getattr(request.state, "principal", None), "source", source_id)
    return current_service(request).source_records(source_id, query, date, offset, limit, kind=kind, tag=tag, tags=tags, match=match)


@router.get("/api/data/files/{source_id}/governance")
def source_file_governance(source_id: str, request: Request):
    require_scope(getattr(request.state, "principal", None), "source", source_id)
    try:
        report = current_service(request).source_file_governance(source_id)
    except DataServiceError as error:
        raise HTTPException(503, "文件质量证据暂时不可用，请重试", headers={"Retry-After": "5"}) from error
    if report is None:
        raise HTTPException(404, "来源文件不存在")
    return report
