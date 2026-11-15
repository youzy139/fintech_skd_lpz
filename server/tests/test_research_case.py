from __future__ import annotations

import json

import pytest

from app.core.serialization import json_compatible
from market_core.models.research import build_research_case, select_research_alert


def alert(rule, day):
    return {"date": day, "rule": rule, "title": rule, "evidence": f"{rule}@{day}", "level": "high"}


def test_selection_prefers_latest_regime_change_over_later_quantile_alerts():
    selected = select_research_alert([
        alert("REGIME_CHANGE", "2024-01-02"),
        alert("HIGH_VOLATILITY", "2024-03-01"),
        alert("REGIME_CHANGE", "2024-02-01"),
    ])
    assert selected["date"] == "2024-02-01"
    assert select_research_alert([alert("HIGH_VOLATILITY", "2024-03-01")])["rule"] == "HIGH_VOLATILITY"
    assert select_research_alert([]) is None


def test_case_preserves_evidence_and_builds_a_two_day_replay_link():
    evidence = {
        "event_time": "2024-02-01", "rule": "REGIME_CHANGE", "rule_version": "rules-test",
        "alert": alert("REGIME_CHANGE", "2024-02-01"),
        "state": {
            "date": "2024-02-01", "label": "高波动避险 · C1", "model_version": "model-test", "trained_through": "2024-01-31",
            "features": {"market_return": -.01, "volatility": .3, "momentum": -.05, "correlation": .7, "trend": -.02, "sample_count": 20},
        },
        "previous_state": {
            "date": "2024-01-31", "label": "震荡平衡 · C0",
            "features": {"market_return": .002, "volatility": .15, "momentum": None, "correlation": .4, "trend": float("nan"), "sample_count": 25},
        },
        "history_days": 60, "parameters": {}, "evidence_links": [],
    }
    case = build_research_case(evidence)
    assert case["case_version"] == "research-case-v1"
    assert case["case_id"] == "case-REGIME_CHANGE-2024-02-01"
    assert case["is_financial_event_label"] is False
    assert case["replay"] == {
        "mode": "local", "start_date": "2024-01-31", "end_date": "2024-02-01",
        "url": "#/replay?start=2024-01-31&end=2024-02-01&mode=local",
        "description": "只带入前后两个状态日的日期与本地通道；由用户决定是否创建并启动真实历史回放。",
    }
    changes = {item["feature"]: item for item in case["feature_changes"]}
    assert changes["volatility"]["delta"] == pytest.approx(.15)
    assert changes["momentum"]["delta"] is None
    assert changes["trend"]["previous"] is None
    assert changes["sample_count"]["delta"] == -5
    assert case["evidence"] is evidence
    assert "25 个变为 20 个（-5）" in case["conclusion"]["coverage_note"]
    assert "不能直接解释为全市场金融事件" in case["conclusion"]["coverage_note"]
    assert "不是人工金融事件标注" in case["conclusion"]["limitations"]
    json.dumps(json_compatible(case), allow_nan=False)


def test_first_alert_without_previous_state_replays_only_the_event_day():
    evidence = {
        "event_time": "2024-01-01", "rule": "HIGH_VOLATILITY", "rule_version": "rules-test",
        "alert": alert("HIGH_VOLATILITY", "2024-01-01"),
        "state": {"date": "2024-01-01", "label": "高波动", "model_version": "model", "trained_through": "2023-12-29", "features": {}},
        "previous_state": None,
    }
    case = build_research_case(evidence)
    assert case["replay"]["start_date"] == "2024-01-01"
    assert all(item["delta"] is None for item in case["feature_changes"])
