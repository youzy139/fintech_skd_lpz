from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

COVERAGE_SENSITIVITY_VERSION = "coverage-sensitivity-v1"
COVERAGE_RULES = ("HIGH_VOLATILITY", "HIGH_CORRELATION", "REGIME_CHANGE")


def _sample_count(state: Mapping[str, Any]) -> float | None:
    value = state.get("features", {}).get("sample_count")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def evaluate_coverage_sensitivity(
    states: Sequence[Mapping[str, Any]],
    alerts: Sequence[Mapping[str, Any]],
    periods: Mapping[str, Mapping[str, Any]],
    thresholds: Sequence[int] = (1, 5, 10, 20, 31),
) -> dict[str, Any]:
    if not thresholds or any(int(value) < 1 for value in thresholds):
        raise ValueError("覆盖门槛必须为正整数")
    normalized = sorted({int(value) for value in thresholds})
    results: dict[str, list[dict[str, Any]]] = {}
    for period, definition in periods.items():
        start = definition.get("start")
        end = definition.get("end")
        selected_states = [state for state in states if (start is None or state["date"] >= start) and (end is None or state["date"] <= end)]
        selected_alerts = [alert for alert in alerts if (start is None or alert["date"] >= start) and (end is None or alert["date"] <= end)]
        rows = []
        for threshold in normalized:
            eligible_dates = {state["date"] for state in selected_states if (_sample_count(state) or 0) >= threshold}
            counts = {}
            for rule in COVERAGE_RULES:
                original = sum(alert["rule"] == rule for alert in selected_alerts)
                retained = sum(alert["rule"] == rule and alert["date"] in eligible_dates for alert in selected_alerts)
                counts[rule] = {"original": original, "retained": retained, "excluded": original - retained}
            rows.append({
                "minimum_sample_count": threshold,
                "state_days": len(selected_states),
                "eligible_days": len(eligible_dates),
                "excluded_days": len(selected_states) - len(eligible_dates),
                "eligible_share": len(eligible_dates) / len(selected_states) if selected_states else None,
                "alerts": counts,
            })
        results[period] = rows
    return {
        "coverage_sensitivity_version": COVERAGE_SENSITIVITY_VERSION,
        "method": "output_filter_only_no_refit",
        "thresholds": normalized,
        "periods": results,
        "limitations": "只按当日有效收益资产数过滤既有状态日和预警，不重训、不删除原始数据、不重新拼接状态或产生跨缺口切换。门槛是敏感性分析，不是推荐生产配置。",
    }
