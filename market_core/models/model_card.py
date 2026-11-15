from __future__ import annotations

import statistics
from typing import Any, Sequence

import pandas as pd

from market_core.domain.market import AssetSeries

MODEL_CARD_VERSION = "model-card-v1"


def _distribution(values: pd.Series) -> dict[str, float | int | None]:
    valid = [float(value) for value in values if pd.notna(value)]
    if not valid:
        return {"min": None, "median": None, "max": None, "latest": None}
    return {
        "min": min(valid),
        "median": float(statistics.median(valid)),
        "max": max(valid),
        "latest": valid[-1],
    }


def build_model_card(
    series: Sequence[AssetSeries],
    features: pd.DataFrame,
    reference_states: Sequence[dict[str, Any]],
    analysis_start: str,
    catalog_missing_assets: Sequence[str] = (),
) -> dict[str, Any]:
    start = pd.Timestamp(analysis_start)
    assets = []
    close_dates: set[pd.Timestamp] = set()
    for item in series:
        frame = item.frame
        values = frame["value"]
        dates = pd.to_datetime(frame["date"])
        included = item.meta.field == "close"
        if included:
            close_dates.update(pd.Timestamp(day) for day in dates if pd.Timestamp(day) >= start)
        valid_rows = len(frame)
        declared_rows = item.meta.declared_rows
        assets.append({
            "code": item.meta.code,
            "name": item.meta.name,
            "category": item.meta.category,
            "field": item.meta.field,
            "model_input": included,
            "exclusion_reason": None if included else "yield 是百分数，不作为价格进入收益、相关性或状态模型",
            "declared_start": item.meta.declared_start.isoformat(),
            "declared_end": item.meta.declared_end.isoformat(),
            "observed_start": dates.min().date().isoformat() if valid_rows else None,
            "observed_end": dates.max().date().isoformat() if valid_rows else None,
            "declared_rows": declared_rows,
            "valid_rows": valid_rows,
            "analysis_rows": int((dates >= start).sum()),
            "observed_vs_declared": valid_rows / declared_rows if declared_rows > 0 else None,
            "positive_rows": int((values > 0).sum()),
            "nonpositive_rows": int((values <= 0).sum()),
            "invalid_rows": item.invalid_rows,
            "duplicate_dates": item.duplicate_dates,
        })
    ordered_dates = sorted(close_dates)
    feature_dates = set(pd.Timestamp(day) for day in features.index)
    first_feature = pd.Timestamp(features.index[0]) if len(features) else None
    last_feature = pd.Timestamp(features.index[-1]) if len(features) else None
    post_first_dates = [day for day in ordered_dates if first_feature is not None and day >= first_feature]
    covered_after_first = sum(day in feature_dates for day in post_first_dates)
    sample_count = features["sample_count"] if "sample_count" in features else pd.Series(dtype=float)
    if reference_states:
        state_start = pd.Timestamp(reference_states[0]["date"])
        state_end = pd.Timestamp(reference_states[-1]["date"])
        state_samples = sample_count.loc[(sample_count.index >= state_start) & (sample_count.index <= state_end)]
    else:
        state_samples = sample_count.iloc[0:0]
    price_assets = sum(asset["model_input"] for asset in assets)
    return {
        "model_card_version": MODEL_CARD_VERSION,
        "intended_use": "多资产历史市场状态监控、证据复核与参数稳定性研究。",
        "out_of_scope": "不提供实时行情、买卖指令、自动交易、预测准确率或投资收益承诺。",
        "analysis_start": start.date().isoformat(),
        "observed_through": max(ordered_dates).date().isoformat() if ordered_dates else None,
        "loaded_series": len(assets),
        "price_assets": price_assets,
        "excluded_series": len(assets) - price_assets,
        "catalog_missing_assets": list(catalog_missing_assets),
        "valid_observations": sum(asset["valid_rows"] for asset in assets),
        "price_observations": sum(asset["valid_rows"] for asset in assets if asset["model_input"]),
        "nonpositive_price_rows": sum(asset["nonpositive_rows"] for asset in assets if asset["model_input"]),
        "invalid_rows": sum(asset["invalid_rows"] for asset in assets),
        "duplicate_dates": sum(asset["duplicate_dates"] for asset in assets),
        "union_price_observation_days": len(ordered_dates),
        "first_feature_day": first_feature.date().isoformat() if first_feature is not None else None,
        "last_feature_day": last_feature.date().isoformat() if last_feature is not None else None,
        "feature_days": len(features),
        "post_first_feature_union_days": len(post_first_dates),
        "covered_after_first_feature_days": covered_after_first,
        "dropped_after_first_feature_days": len(post_first_dates) - covered_after_first,
        "dropped_after_first_feature_dates": [day.date().isoformat() for day in post_first_dates if day not in feature_dates],
        "post_first_feature_coverage": covered_after_first / len(post_first_dates) if post_first_dates else None,
        "feature_sample_count": _distribution(sample_count),
        "state_days": len(reference_states),
        "state_sample_count": _distribution(state_samples),
        "state_days_below_price_assets": int((state_samples < price_assets).sum()),
        "assets": assets,
        "limitations": [
            "资产覆盖来自清洗后的有效序列；目录条数对照不替代按各资产交易日历开展的完整性审计。",
            "sample_count 是当日具有有效对数收益的资产数，不是全部目录资产或有价格资产数。",
            "首个完整特征日后的缺口表示四个模型输入至少一项缺失；本报告不进一步归因于特定资产或特征。",
            "非正价格、无效行和重复日期有独立计数；语义异常、复权合理性和跨源一致性仍未评估。",
        ],
    }
