from __future__ import annotations

from fastapi import APIRouter, Query as QueryParam, Request

from app.api.dependencies import current_service

router = APIRouter(tags=["data"])


@router.get("/api/data/summary")
def source_summary(request: Request):
    return current_service(request).source_summary()


@router.get("/api/data/overview")
def source_overview(request: Request, kind: str | None = None):
    return current_service(request).source_overview(kind)


@router.get("/api/data/tags")
def source_tags(request: Request, kind: str | None = None):
    return current_service(request).source_tags(kind)


@router.get("/api/data/records")
def records(request: Request, kind: str | None = None, query: str | None = None, date: str | None = None, tag: str | None = None, tags: list[str] = QueryParam(default=[], max_length=5), match: str = QueryParam("any", pattern="^(any|all)$"), offset: int = QueryParam(0, ge=0), limit: int = QueryParam(20, ge=1, le=100)):
    return current_service(request).source_records(None, query, date, offset, limit, kind, tag, tags, match)


@router.get("/api/data/files")
def source_files(request: Request, kind: str | None = None, query: str | None = None, offset: int = QueryParam(0, ge=0), limit: int = QueryParam(50, ge=1, le=100)):
    return current_service(request).source_files(kind, query, offset, limit)


@router.get("/api/data/files/{source_id}/records")
def source_records(source_id: str, request: Request, query: str | None = None, date: str | None = None, tag: str | None = None, tags: list[str] = QueryParam(default=[], max_length=5), match: str = QueryParam("any", pattern="^(any|all)$"), offset: int = QueryParam(0, ge=0), limit: int = QueryParam(20, ge=1, le=100)):
    return current_service(request).source_records(source_id, query, date, offset, limit, tag=tag, tags=tags, match=match)
