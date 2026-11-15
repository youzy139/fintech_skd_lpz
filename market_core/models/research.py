from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

RESEARCH_CASE_VERSION = "research-case-v1"


def select_research_alert(alerts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    changes = sorted((alert for alert in alerts if alert.get("rule") == "REGIME_CHANGE"), key=lambda alert: str(alert["date"]))
    if changes:
        return changes[-1]
    ordered = sorted(alerts, key=lambda alert: str(alert["date"]))
    return ordered[-1] if ordered else None


def _finite(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def _feature_changes(state: Mapping[str, Any], previous: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    current_features = state.get("features", {})
    previous_features = previous.get("features", {}) if previous else {}
    changes = []
    for name in ("market_return", "volatility", "momentum", "correlation", "trend", "sample_count"):
        current = _finite(current_features.get(name))
        before = _finite(previous_features.get(name))
        changes.append({"feature": name, "current": current, "previous": before, "delta": current - before if current is not None and before is not None else None})
    return changes


def build_research_case(evidence: Mapping[str, Any]) -> dict[str, Any]:
    state = evidence["state"]
    previous = evidence.get("previous_state")
    alert = evidence["alert"]
    event_date = str(evidence["event_time"])
    replay_start = str(previous["date"]) if previous else event_date
    feature_changes = _feature_changes(state, previous)
    sample_change = next(item for item in feature_changes if item["feature"] == "sample_count")
    if sample_change["current"] is None or sample_change["previous"] is None:
        coverage_note = "前后有效收益资产数至少一项缺失，不能比较样本覆盖变化。"
    elif sample_change["delta"] == 0:
        coverage_note = f"前后有效收益资产数均为 {sample_change['current']:.0f} 个；仍需结合各资产观测起点理解覆盖。"
    else:
        coverage_note = f"有效收益资产从 {sample_change['previous']:.0f} 个变为 {sample_change['current']:.0f} 个（{sample_change['delta']:+.0f}）；状态比较同时受样本覆盖变化影响，不能直接解释为全市场金融事件。"
    return {
        "case_version": RESEARCH_CASE_VERSION,
        "case_id": f"case-{evidence['rule']}-{event_date}",
        "selection_policy": "latest_regime_change_else_latest_alert",
        "title": f"{alert['title']}复核 · {event_date}",
        "event_time": event_date,
        "is_financial_event_label": False,
        "feature_changes": feature_changes,
        "replay": {
            "mode": "local",
            "start_date": replay_start,
            "end_date": event_date,
            "url": f"#/replay?start={replay_start}&end={event_date}&mode=local",
            "description": "只带入前后两个状态日的日期与本地通道；由用户决定是否创建并启动真实历史回放。",
        },
        "conclusion": {
            "observation": alert["evidence"],
            "statistical_evidence": f"当前规则版本 {evidence['rule_version']}，模型版本 {state['model_version']}，训练数据截至 {state['trained_through']}。",
            "validation": "通过前后特征、当时可见背景和逐日真实回放复核计算过程；回放不是实时行情。",
            "coverage_note": coverage_note,
            "limitations": "这是确定性规则案例，不是人工金融事件标注、因果解释、预测准确率或买卖建议。",
        },
        "evidence": evidence,
    }
