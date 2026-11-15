from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from itertools import combinations
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from market_core.models.regime import REGIME_IDENTITY, WalkForwardRegimeModel

EVALUATION_VERSION = "stability-v1"
PROTOCOL_VERSION = "evaluation-v1-draft"
PERIOD_DEFINITIONS = {
    "all": {"label": "全部历史", "start": None, "end": None},
    "development": {"label": "开发区间", "start": "2017-01-01", "end": "2021-12-31"},
    "validation": {"label": "验证区间", "start": "2022-01-01", "end": "2024-12-31"},
    "holdout": {"label": "操作留出区间", "start": "2025-01-01", "end": "2026-04-30"},
}


def semantic_label(label: str) -> str:
    return label.rsplit(" · C", 1)[0] if " · C" in label else label


def _period_states(states: Sequence[Mapping[str, Any]], period: str) -> list[Mapping[str, Any]]:
    definition = PERIOD_DEFINITIONS[period]
    return [
        state for state in states
        if (definition["start"] is None or state["date"] >= definition["start"])
        and (definition["end"] is None or state["date"] <= definition["end"])
    ]


def summarize_states(states: Sequence[Mapping[str, Any]], period: str = "all") -> dict[str, Any]:
    selected = _period_states(states, period)
    if not selected:
        return {
            "state_days": 0, "first_state": None, "last_state": None,
            "switch_count": 0, "switches_per_100_state_days": None,
            "refit_boundary_count": 0, "refit_boundary_switch_count": 0,
            "refit_boundary_switch_share": None, "refit_boundary_switch_rate": None,
            "episode_count": 0, "median_duration_days": None,
            "p90_duration_days": None, "max_duration_days": None,
            "semantic_distribution": {},
        }
    switches = 0
    refit_boundaries = 0
    refit_switches = 0
    durations: list[int] = []
    duration = 1
    for previous, current in zip(selected, selected[1:]):
        changed = current["label"] != previous["label"]
        refit = current["trained_through"] != previous["trained_through"]
        switches += int(changed)
        refit_boundaries += int(refit)
        refit_switches += int(changed and refit)
        if changed:
            durations.append(duration)
            duration = 1
        else:
            duration += 1
    durations.append(duration)
    return {
        "state_days": len(selected),
        "first_state": selected[0]["date"],
        "last_state": selected[-1]["date"],
        "switch_count": switches,
        "switches_per_100_state_days": switches * 100 / len(selected),
        "refit_boundary_count": refit_boundaries,
        "refit_boundary_switch_count": refit_switches,
        "refit_boundary_switch_share": refit_switches / switches if switches else None,
        "refit_boundary_switch_rate": refit_switches / refit_boundaries if refit_boundaries else None,
        "episode_count": len(durations),
        "median_duration_days": float(statistics.median(durations)),
        "p90_duration_days": float(np.percentile(durations, 90)),
        "max_duration_days": max(durations),
        "semantic_distribution": dict(sorted(Counter(semantic_label(str(state["label"])) for state in selected).items())),
    }


def compare_states(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]], period: str = "all") -> dict[str, Any]:
    left_by_date = {state["date"]: state for state in _period_states(left, period)}
    right_by_date = {state["date"]: state for state in _period_states(right, period)}
    dates = sorted(left_by_date.keys() & right_by_date.keys())
    if not dates:
        return {
            "common_state_days": 0, "common_start": None, "common_end": None,
            "adjusted_rand_index": None, "semantic_agreement": None,
        }
    left_ids = [int(left_by_date[day].get("regime_id", left_by_date[day].get("cluster", -1))) for day in dates]
    right_ids = [int(right_by_date[day].get("regime_id", right_by_date[day].get("cluster", -1))) for day in dates]
    semantic_matches = sum(
        semantic_label(str(left_by_date[day]["label"])) == semantic_label(str(right_by_date[day]["label"]))
        for day in dates
    )
    return {
        "common_state_days": len(dates),
        "common_start": dates[0],
        "common_end": dates[-1],
        "adjusted_rand_index": float(adjusted_rand_score(left_ids, right_ids)),
        "semantic_agreement": semantic_matches / len(dates),
    }


def _distribution(values: Iterable[float | None]) -> dict[str, float | None]:
    finite = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not finite:
        return {"min": None, "median": None, "max": None}
    return {"min": min(finite), "median": float(statistics.median(finite)), "max": max(finite)}


def evaluate_stability(
    features: pd.DataFrame,
    settings: Mapping[str, Any],
    training_windows: Sequence[int] = (504, 756),
    refit_intervals: Sequence[int] = (63, 126),
    random_seeds: Sequence[int] = (42, 2026),
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    if not training_windows or not refit_intervals or not random_seeds:
        raise ValueError("稳定性评估网格不能为空")
    if any(int(value) < 2 for value in training_windows) or any(int(value) < 1 for value in refit_intervals):
        raise ValueError("训练窗口至少为 2，重训间隔必须为正数")
    if len(set(training_windows)) != len(training_windows) or len(set(refit_intervals)) != len(refit_intervals) or len(set(random_seeds)) != len(random_seeds):
        raise ValueError("稳定性评估网格不能包含重复组合参数")
    minimum_history = int(settings["minimum_history"])
    if len(features) <= minimum_history:
        raise ValueError("有效特征日不足以生成稳定性评估")
    identity = str(settings.get("regime_identity", REGIME_IDENTITY))
    if identity != REGIME_IDENTITY:
        raise ValueError("跨参数稳定性评估要求使用 centroid-alignment-v1")
    experiments = [
        {
            "run_id": f"w{window}-r{interval}-s{seed}",
            "training_window": int(window),
            "refit_interval": int(interval),
            "random_seed": int(seed),
        }
        for window in training_windows
        for interval in refit_intervals
        for seed in random_seeds
    ]
    reference_run_id = f"w{int(settings['training_window'])}-r{int(settings['refit_interval'])}-s{int(settings['random_seed'])}"
    if reference_run_id not in {experiment["run_id"] for experiment in experiments}:
        raise ValueError("评估网格必须包含当前基准参数")
    histories: dict[str, list[dict[str, Any]]] = {}
    daily: dict[str, list[dict[str, Any]]] = {}
    runs = []
    for experiment in experiments:
        model = WalkForwardRegimeModel(
            minimum_history,
            experiment["training_window"],
            experiment["refit_interval"],
            int(settings["cluster_count"]),
            experiment["random_seed"],
            identity,
        )
        states = model.predict(features)
        run_id = experiment["run_id"]
        histories[run_id] = states
        daily[run_id] = [
            {
                "date": state["date"], "regime_id": state["regime_id"], "label": state["label"],
                "cluster": state["cluster"], "trained_through": state["trained_through"],
                "model_version": state["model_version"],
            }
            for state in states
        ]
        runs.append({
            **experiment,
            "is_reference": run_id == reference_run_id,
            "periods": {period: summarize_states(states, period) for period in PERIOD_DEFINITIONS},
        })
    comparisons = []
    for period in PERIOD_DEFINITIONS:
        for left, right in combinations((experiment["run_id"] for experiment in experiments), 2):
            comparisons.append({
                "period": period, "left_run_id": left, "right_run_id": right,
                **compare_states(histories[left], histories[right], period),
            })
    summary = {}
    for period in PERIOD_DEFINITIONS:
        selected = [item for item in comparisons if item["period"] == period]
        summary[period] = {
            "pair_count": len(selected),
            "common_state_days": _distribution(item["common_state_days"] for item in selected),
            "adjusted_rand_index": _distribution(item["adjusted_rand_index"] for item in selected),
            "semantic_agreement": _distribution(item["semantic_agreement"] for item in selected),
        }
    feature_sha256 = hashlib.sha256(pd.util.hash_pandas_object(features, index=True).values.tobytes()).hexdigest()
    identity_payload = {
        "evaluation_version": EVALUATION_VERSION,
        "feature_sha256": feature_sha256,
        "fixed": {"minimum_history": minimum_history, "cluster_count": int(settings["cluster_count"]), "regime_identity": identity},
        "grid": {"training_windows": list(training_windows), "refit_intervals": list(refit_intervals), "random_seeds": list(random_seeds)},
        "periods": PERIOD_DEFINITIONS,
    }
    evaluation_id = "stability-" + hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    report = {
        "schema_version": 1,
        "report_type": "regime_stability",
        "evaluation_version": EVALUATION_VERSION,
        "evaluation_id": evaluation_id,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_status": "draft_pending_team_review",
        "reference_run_id": reference_run_id,
        "feature_sha256": feature_sha256,
        "feature_days": len(features),
        "fixed": identity_payload["fixed"],
        "grid": {**identity_payload["grid"], "run_count": len(experiments)},
        "period_definitions": PERIOD_DEFINITIONS,
        "runs": runs,
        "comparisons": comparisons,
        "summary": summary,
        "metric_definitions": {
            "adjusted_rand_index": "共同日期状态分区的调整兰德指数；对簇编号置换不变，不是预测准确率。",
            "semantic_agreement": "共同日期去除稳定身份后缀后的语义标签一致率；同名状态不保证中心画像相同。",
            "switches_per_100_state_days": "区间内完整标签相对前一区间内状态日发生变化的次数 / 区间状态日 × 100。",
            "duration": "按区间内完整标签连续段计算持续期，区间边界会截断持续段。",
            "refit_boundary_switch_share": "发生在训练截止日变化边界的切换数 / 全部切换数；另列边界切换率，分母为重训边界数。",
        },
        "limitations": [
            "本报告只衡量参数扰动下的历史状态稳定性，不证明金融事件命中率、预测准确率或投资效果。",
            "全部历史曾用于工程验证；留出区间仅表示本评估的操作隔离，不宣称从未查看过。",
            "评估协议仍待团队复核；事件标注、预警 episode 匹配和误报评估尚未完成。",
        ],
    }
    return report, daily
