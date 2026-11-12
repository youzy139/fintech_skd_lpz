from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import pandas as pd

from market_core.domain.market import AssetSeries
from market_core.models.features import FEATURE_COLUMNS
from market_core.models.regime import REGIME_IDENTITY

FEATURE_ALGORITHM = "market-features-v1"


def content_version(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return prefix + hashlib.sha256(encoded).hexdigest()


def model_parameters(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis_start": pd.Timestamp(settings["analysis_start"]).date().isoformat(),
        **{name: int(settings[name]) for name in (
            "minimum_history", "training_window", "refit_interval", "volatility_window",
            "momentum_window", "cluster_count", "random_seed",
        )},
        "regime_identity": settings.get("regime_identity", REGIME_IDENTITY),
    }


def feature_contract(settings: dict[str, Any]) -> dict[str, Any]:
    volatility_window = int(settings["volatility_window"])
    momentum_window = int(settings["momentum_window"])
    definitions = [
        {"name": "market_return", "title": "市场收益", "unit": "log_return", "window": 1, "minimum_observations": 2,
         "formula": "各正价格资产相邻观测行对数收益的横截面均值；两行均须有有效价格。"},
        {"name": "volatility", "title": "年化波动率", "unit": "annualized_ratio", "window": volatility_window, "minimum_observations": volatility_window,
         "formula": f"市场收益在 {volatility_window} 行窗口内的样本标准差（ddof=1）乘 √252。"},
        {"name": "momentum", "title": "中期动量", "unit": "ratio", "window": momentum_window, "minimum_observations": momentum_window + 1,
         "formula": f"各价格资产当前值相对 {momentum_window} 行前价格涨跌幅的横截面均值。"},
        {"name": "correlation", "title": "资产相关性", "unit": "coefficient", "window": momentum_window, "minimum_observations": 20,
         "formula": f"最近 {momentum_window} 行资产对数收益的 Pearson 成对相关系数均值；每对至少 20 个共同有效观测，排除对角线和非有限系数。"},
        {"name": "trend", "title": "短期趋势", "unit": "ratio", "window": volatility_window, "minimum_observations": volatility_window,
         "formula": f"各价格资产相对 {volatility_window} 行简单均线偏离的横截面均值。"},
        {"name": "sample_count", "title": "有效收益资产数", "unit": "assets", "window": 1, "minimum_observations": 2,
         "formula": "当行非缺失对数收益的资产数量，不等于全部资产数量。"},
    ]
    payload = {
        "schema_version": 1,
        "algorithm": FEATURE_ALGORITHM,
        "analysis_start": pd.Timestamp(settings["analysis_start"]).date().isoformat(),
        "input": "仅 field=close 的行情；yield 不进入价格特征。",
        "time_basis": "按所有价格资产观测日期外连接的行数计窗口，不填充缺失交易日；日频数据未核实盘中公布时间，不作盘中可见性承诺。",
        "visibility": "特征日只读取该事件日期及此前行情；状态训练排除识别当日。",
        "missing_policy": "不前向填充；横截面均值跳过缺失；四个模型输入任一缺失则不产出特征行；接口非有限值输出 null。",
        "features": [{**item, "model_input": item["name"] in FEATURE_COLUMNS} for item in definitions],
    }
    return {**payload, "feature_version": content_version("features-", payload)}


def market_input_version(series: list[AssetSeries], through: date | None = None) -> str:
    digest = hashlib.sha256(b"market-input-v1\n")
    for item in series:
        frame = item.frame
        if through is not None:
            frame = frame.loc[frame["date"] <= pd.Timestamp(through)]
        if frame.empty:
            continue
        # Preserve computation order; paths, display names and future rows are not inputs.
        digest.update(json.dumps([item.meta.code, item.meta.field], ensure_ascii=False).encode("utf-8") + b"\n")
        for day, value in zip(frame["date"], frame["value"]):
            digest.update(f"{pd.Timestamp(day).isoformat()}|{float(value).hex()}\n".encode("ascii"))
    return "market-input-" + digest.hexdigest()
