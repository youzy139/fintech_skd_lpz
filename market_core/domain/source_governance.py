from __future__ import annotations

from copy import deepcopy
from typing import Any


SOURCE_POLICIES = {
    "asset": ("资产行情", "model", "观测日；没有盘中发布时间，收盘价进入模型，收益率字段不作价格", "按事件日期输入；正价格及有效观测由行情加载器校验"),
    "calendar": ("宏观日历", "background", "OccurDate/OccurTime；本地日期尚未统一为带时区发布时间", "仅在前一状态日及以前关联背景，不进入模型或规则"),
    "publication": ("公众号", "background", "原始日期字段；没有精确发布时间", "仅在前一状态日及以前关联背景，不进入模型或规则"),
    "commodity": ("商品成交", "catalog_only", "统计日期，不等同于公布时间", "仅目录检索；公布时间与建模单位需专项核实"),
    "indicator": ("脱敏指标", "catalog_only", "各 Sheet 原始统计日期；字段含义未核实", "保留全部 Sheet，不推断经济含义或强制日频"),
    "news": ("新闻", "catalog_only", "原始第 10 列解析的日期；字段字典和时区未核实", "只校验 11 列并保留 column_N，禁止据此加入核心判断"),
    "research": ("研究摘要", "catalog_only", "文件名日期，非已核实发布时间", "保留原始名称来源；发布时间核实前仅供检索"),
    "social": ("社交媒体", "catalog_only", "created_at_twitter 日期；时区与可见时间未统一核实", "发布时间核实前仅供检索，不推断情绪或因果"),
}

LIFECYCLE_POLICY = {
    "status": "manual-retention",
    "retention_days": None,
    "automatic_delete": False,
    "raw": "原始文件只读保留；期限待团队确认，不自动删除或覆盖",
    "online": "当前目录保留在线记录；导入/发布按已有流程执行",
    "archive": "MinIO 原始对象归档沿用已启用的部署路径；本报告不执行归档或核验对象",
    "recompute": "解析或时间语义改变后，在隔离目录重算并核对摘要，批准后按原发布流程切换",
    "delete": "删除须先完成备份、引用核对和用户授权，并在隔离副本演练；本批没有删除执行器",
}


def source_policy(kind: str) -> dict[str, Any]:
    name, usage, time_semantics, restriction = SOURCE_POLICIES.get(
        kind, (kind, "catalog_only", "未核实", "未知类型隔离，不进入模型、规则或背景证据"),
    )
    return {
        "kind": kind, "name": name, "usage": usage,
        "time_semantics": time_semantics, "restriction": restriction,
        "lifecycle": deepcopy(LIFECYCLE_POLICY),
    }
