from __future__ import annotations

import pandas as pd

from market_core.domain.market import Alert


def generate_alerts(states: list[dict], volatility_quantile: float, correlation_quantile: float) -> list[Alert]:
    if not states:
        return []
    frame = pd.DataFrame({"date": [item["date"] for item in states], "volatility": [item["features"]["volatility"] for item in states], "correlation": [item["features"]["correlation"] for item in states]})
    alerts: list[Alert] = []
    for index, state in enumerate(states):
        history = frame.iloc[:index]
        if state["features"]["volatility"] >= history["volatility"].quantile(volatility_quantile) and len(history) >= 60:
            value = state["features"]["volatility"]
            threshold = float(history["volatility"].quantile(volatility_quantile))
            alerts.append(Alert(state["date"], "HIGH_VOLATILITY", "high", "市场波动率异常", f"年化波动率 {value:.2%}，超过历史 {volatility_quantile:.0%} 分位", value, threshold))
        if state["features"]["correlation"] >= history["correlation"].quantile(correlation_quantile) and len(history) >= 60:
            value = state["features"]["correlation"]
            threshold = float(history["correlation"].quantile(correlation_quantile))
            alerts.append(Alert(state["date"], "HIGH_CORRELATION", "medium", "资产相关性异常", f"平均相关性 {value:.3f}，超过历史 {correlation_quantile:.0%} 分位", value, threshold))
        if index and state["label"] != states[index - 1]["label"]:
            alerts.append(Alert(state["date"], "REGIME_CHANGE", "high", "市场状态切换", f"{states[index - 1]['label']} → {state['label']}"))
    return alerts
