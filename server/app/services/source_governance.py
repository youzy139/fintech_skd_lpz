from __future__ import annotations

from typing import Any

from app.services.remote_catalog import DataServiceError
from market_core.domain.source_governance import SOURCE_POLICIES, source_policy


def governance_report(catalog: Any, kind: str | None = None) -> dict[str, Any]:
    version = catalog.data_version()
    summary = catalog.summary()
    kinds = [kind] if kind else sorted(set(SOURCE_POLICIES) | {group["kind"] for group in summary["groups"]})
    items = []
    for source_kind in kinds:
        overview = catalog.overview(source_kind)
        records, undated = overview["records"], overview["undated_records"]
        consistent = 0 <= undated <= records
        items.append({
            **source_policy(source_kind),
            "files": overview["files"], "records": records,
            "start_date": overview["start_date"], "end_date": overview["end_date"],
            "undated_records": undated,
            "undated_ratio": undated / records if records and consistent else None,
            "statistics_status": "consistent" if consistent else "inconsistent",
            "fields": overview["fields"], "field_limit": 100,
            "field_inventory_may_be_truncated": len(overview["fields"]) >= 100,
            "duplicate_records": None, "invalid_records": None,
        })
    if catalog.data_version() != version:
        raise DataServiceError("目录版本发生变化，请重试")
    return {
        "schema": "source-governance-v1", "policy_version": "source-policy-v1",
        "data_version": version, "scope": "source-kind", "kind": kind,
        "summary": summary, "items": items,
        "limitations": [
            "按来源类型聚合，不是逐文件、逐资产或逐行的质量审计",
            "逻辑记录数不是有效行情数；文件级导入错误不是无效记录数",
            "无日期表示当前解析结果缺少事件日期，不等于全部时间异常",
            "字段统计最多 100 项；非空数按类型全部记录统计，不等于必填字段完整率",
            "重复和异常记录数未评估，以 null 表示，不能视为零",
            "本报告登记保留策略，不执行归档、删除或重算，也不改变模型输入",
        ],
    }
