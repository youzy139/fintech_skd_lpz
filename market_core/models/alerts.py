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
        volatility = state["features"]["volatility"]
        if len(history) >= 60 and volatility is not None and volatility >= history["volatility"].quantile(volatility_quantile):
            threshold = float(history["volatility"].quantile(volatility_quantile))
            alerts.append(Alert(state["date"], "HIGH_VOLATILITY", "high", "市场波动率异常", f"年化波动率 {volatility:.2%}，超过历史 {volatility_quantile:.0%} 分位", volatility, threshold))
        correlation = state["features"]["correlation"]
        if len(history) >= 60 and correlation is not None and correlation >= history["correlation"].quantile(correlation_quantile):
            threshold = float(history["correlation"].quantile(correlation_quantile))
            alerts.append(Alert(state["date"], "HIGH_CORRELATION", "medium", "资产相关性异常", f"平均相关性 {correlation:.3f}，超过历史 {correlation_quantile:.0%} 分位", correlation, threshold))
        if index and state["label"] != states[index - 1]["label"]:
            alerts.append(Alert(state["date"], "REGIME_CHANGE", "high", "市场状态切换", f"{states[index - 1]['label']} → {state['label']}"))
    return alerts
