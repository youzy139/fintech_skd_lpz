from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from market_core.domain.market import Alert


def normalize_rule_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "volatility_quantile": float(settings.get("volatility_quantile", 0.9)),
        "correlation_quantile": float(settings.get("correlation_quantile", 0.9)),
        "minimum_history": int(settings.get("minimum_history", 60)),
        "regime_change_enabled": bool(settings.get("regime_change_enabled", True)),
    }
    for name in ("volatility_quantile", "correlation_quantile"):
        if not 0.5 <= normalized[name] <= 0.99:
            raise ValueError("预警分位数必须在 0.50 到 0.99 之间")
    if not 10 <= normalized["minimum_history"] <= 1000:
        raise ValueError("预警历史窗口必须在 10 到 1000 个状态日之间")
    return normalized


def alert_rule_version(settings: dict[str, Any]) -> str:
    normalized = normalize_rule_settings(settings)
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return "rules-" + digest[:16]


def generate_alerts(
    states: list[dict], volatility_quantile: float, correlation_quantile: float,
    minimum_history: int = 60, regime_change_enabled: bool = True, rule_version: str | None = None,
) -> list[Alert]:
    if not states:
        return []
    settings = normalize_rule_settings({
        "volatility_quantile": volatility_quantile,
        "correlation_quantile": correlation_quantile,
        "minimum_history": minimum_history,
        "regime_change_enabled": regime_change_enabled,
    })
    version = rule_version or alert_rule_version(settings)
    frame = pd.DataFrame({"date": [item["date"] for item in states], "volatility": [item["features"]["volatility"] for item in states], "correlation": [item["features"]["correlation"] for item in states]})
    alerts: list[Alert] = []
    for index, state in enumerate(states):
        history = frame.iloc[:index]
        volatility = state["features"]["volatility"]
        if len(history) >= settings["minimum_history"] and volatility is not None and volatility >= history["volatility"].quantile(settings["volatility_quantile"]):
            threshold = float(history["volatility"].quantile(settings["volatility_quantile"]))
            alerts.append(Alert(state["date"], "HIGH_VOLATILITY", "high", "市场波动率异常", f"年化波动率 {volatility:.2%}，超过历史 {settings['volatility_quantile']:.0%} 分位", volatility, threshold, version))
        correlation = state["features"]["correlation"]
        if len(history) >= settings["minimum_history"] and correlation is not None and correlation >= history["correlation"].quantile(settings["correlation_quantile"]):
            threshold = float(history["correlation"].quantile(settings["correlation_quantile"]))
            alerts.append(Alert(state["date"], "HIGH_CORRELATION", "medium", "资产相关性异常", f"平均相关性 {correlation:.3f}，超过历史 {settings['correlation_quantile']:.0%} 分位", correlation, threshold, version))
        if settings["regime_change_enabled"] and index and state["label"] != states[index - 1]["label"]:
            alerts.append(Alert(state["date"], "REGIME_CHANGE", "high", "市场状态切换", f"{states[index - 1]['label']} → {state['label']}", rule_version=version))
    return alerts


def alert_evidence(states: list[dict], alerts: list[dict], rule: str, event_date: str, settings: dict[str, Any]) -> dict[str, Any]:
    index = next((index for index, item in enumerate(states) if item["date"] == event_date), None)
    alert = next((item for item in alerts if item["rule"] == rule and item["date"] == event_date), None)
    if index is None or alert is None:
        raise KeyError(f"{rule}:{event_date}")
    normalized = normalize_rule_settings(settings)
    return {
        "event_time": event_date,
        "rule": rule,
        "rule_version": alert.get("rule_version") or alert_rule_version(normalized),
        "alert": alert,
        "state": states[index],
        "previous_state": states[index - 1] if index else None,
        "history_days": index,
        "parameters": normalized,
        "evidence_links": [{"type": "market_state", "url": f"/api/regimes?start={event_date}&end={event_date}"}],
    }
