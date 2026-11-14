from __future__ import annotations

import logging
from typing import Any, Collection

from app.services.contracts import CatalogReader


SOURCE_TYPES = {
    "calendar": "经济日历的 OccurDate 与 OccurTime；来源未提供时区",
    "publication": "公众号记录的来源日期；未提供具体时刻",
}
EXCLUDED_TYPES = [
    {"kind": "news", "reason": "赛题未提供 11 列字段字典，两个 Unix 时间戳的含义未确认"},
    {"kind": "indicator", "reason": "只有统计日期，没有可核实的公布时间"},
    {"kind": "research", "reason": "只有文件名中的报告日期，不能等同于实际发布时间"},
    {"kind": "social", "reason": "发帖时间与来源时区尚未完成统一核验"},
]


def _public_item(item: dict[str, Any], kind: str) -> dict[str, Any]:
    payload = item["payload"]
    occur_time = str(payload.get("OccurTime") or "") or None
    return {
        "record_id": f"{item['source_id']}:{item['record_index']}",
        "kind": kind,
        "title": item["title"],
        "source_path": item["source_path"],
        "source_date": item["event_date"],
        "source_time": occur_time if kind == "calendar" else None,
        "source_timestamp": f"{item['event_date']}T{occur_time}" if kind == "calendar" and occur_time else None,
        "time_basis": SOURCE_TYPES[kind],
    }


def _context_page(catalog: CatalogReader, kind: str, cutoff: str, limit: int, allowed_sources: Collection[str] | None) -> dict[str, Any]:
    if allowed_sources is None:
        return catalog.list_records(None, None, cutoff, 0, limit, kind=kind)
    total = 0
    items: list[dict[str, Any]] = []
    for source_id in sorted(set(allowed_sources)):
        page = catalog.list_records(source_id, None, cutoff, 0, limit, kind=kind)
        total += int(page["total"])
        items.extend(page["items"])
    items.sort(key=lambda item: (item["source_id"], -item["record_index"]))
    return {"total": total, "items": items[:limit]}


def attach_context(evidence: dict[str, Any], catalog: CatalogReader | None, limit: int = 6, allowed_sources: Collection[str] | None = None) -> dict[str, Any]:
    previous = evidence.get("previous_state")
    cutoff = previous["date"] if previous else None
    context: dict[str, Any] = {
        "cutoff_date": cutoff,
        "policy": "strictly_before_alert_date",
        "description": "只读取预警日前一状态日已经存在的公开背景；不关联当天或未来记录，不用于改变状态与预警。",
        "sources": [],
        "excluded": EXCLUDED_TYPES,
        "source_scope": "all" if allowed_sources is None else "allowlist",
    }
    if allowed_sources is not None:
        context["description"] += " 仅统计当前账号白名单内的来源。"
    if not cutoff:
        context["status"] = "no_previous_state"
        evidence["context"] = context
        return evidence
    if catalog is None:
        context["status"] = "disabled"
        evidence["context"] = context
        return evidence
    context["status"] = "ok"
    for kind in SOURCE_TYPES:
        try:
            page = _context_page(catalog, kind, cutoff, limit, allowed_sources)
            context["sources"].append({
                "kind": kind,
                "status": "ok",
                "total": page["total"],
                "items": [_public_item(item, kind) for item in page["items"]],
            })
        except Exception as error:
            logging.getLogger("marketlens.evidence").warning("context_evidence_unavailable kind=%s error_type=%s", kind, type(error).__name__)
            context["sources"].append({"kind": kind, "status": "unavailable", "total": None, "items": []})
            context["status"] = "degraded"
    evidence["context"] = context
    return evidence
