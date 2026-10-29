from __future__ import annotations

import numpy as np
import pandas as pd

from market_core.domain.market import AssetSeries

FEATURE_COLUMNS = ["market_return", "volatility", "momentum", "correlation"]


def build_price_panels(series: list[AssetSeries]) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = [item.frame.rename(columns={"value": item.meta.code}).set_index("date") for item in series if item.meta.field == "close"]
    if not prices:
        raise ValueError("没有可用于特征计算的价格序列")
    close = pd.concat(prices, axis=1).sort_index()
    positive_close = close.where(close > 0)
    returns = np.log(positive_close / positive_close.shift(1))
    return close, returns


def average_correlation(returns: pd.DataFrame, window: int, start: pd.Timestamp) -> pd.Series:
    values: dict[pd.Timestamp, float] = {}
    dates = returns.index[returns.index >= start]
    columns = returns.columns
    for day in dates:
        sample = returns.loc[:day, columns].tail(window)
        corr = sample.corr(min_periods=20).to_numpy()
        upper = corr[np.triu_indices_from(corr, k=1)]
        valid = upper[np.isfinite(upper)]
        values[day] = float(valid.mean()) if valid.size else np.nan
    return pd.Series(values, name="correlation")


def build_market_features(series: list[AssetSeries], volatility_window: int, momentum_window: int, analysis_start: str, output_start: str | None = None) -> pd.DataFrame:
    close, returns = build_price_panels(series)
    start = pd.Timestamp(analysis_start)
    market_return = returns.mean(axis=1, skipna=True)
    momentum_by_asset = close / close.shift(momentum_window) - 1
    trend_by_asset = close / close.rolling(volatility_window).mean() - 1
    features = pd.DataFrame(
        {
            "market_return": market_return,
            "volatility": market_return.rolling(volatility_window).std() * np.sqrt(252),
            "momentum": momentum_by_asset.mean(axis=1, skipna=True),
            "trend": trend_by_asset.mean(axis=1, skipna=True),
            "sample_count": returns.notna().sum(axis=1),
        }
    )
    correlation_start = pd.Timestamp(output_start) if output_start else start - pd.Timedelta(days=120)
    features["correlation"] = average_correlation(returns, momentum_window, correlation_start)
    features = features.loc[features.index >= start, FEATURE_COLUMNS + ["trend", "sample_count"]]
    if output_start:
        features = features.loc[features.index >= pd.Timestamp(output_start)]
    return features.dropna(subset=FEATURE_COLUMNS)
