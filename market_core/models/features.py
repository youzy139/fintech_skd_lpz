from __future__ import annotations

import numpy as np
import pandas as pd

from market_core.domain.market import AssetSeries

FEATURE_COLUMNS = ["market_return", "volatility", "momentum", "correlation"]


def build_price_panels(series: list[AssetSeries]) -> tuple[pd.DataFrame, pd.DataFrame]:
    priced = [(item.meta.code, item.frame.rename(columns={"value": item.meta.code}).set_index("date")) for item in series if item.meta.field == "close"]
    if not priced:
        raise ValueError("没有可用于特征计算的价格序列")
    # Align by sorted datetime positions instead of repeatedly unioning DatetimeIndex objects.
    date_values = np.unique(np.concatenate([frame.index.to_numpy() for _, frame in priced])) if any(len(frame) for _, frame in priced) else np.array([], dtype="datetime64[ns]")
    close_values = np.full((len(date_values), len(priced)), np.nan)
    for position, (code, frame) in enumerate(priced):
        ordered = frame.sort_index()
        if not ordered.index.is_unique:
            raise ValueError(f"资产 {code} 存在重复日期")
        locations = date_values.searchsorted(ordered.index.to_numpy())
        close_values[locations, position] = ordered[code].to_numpy()
    index = pd.DatetimeIndex(date_values, name="date")
    index.freq = pd.infer_freq(index) if len(index) >= 3 else None
    close = pd.DataFrame(close_values, index=index, columns=[code for code, _ in priced])
    positive_close = close.where(close > 0)
    returns = np.log(positive_close / positive_close.shift(1))
    return close, returns


def average_correlation(returns: pd.DataFrame, window: int, start: pd.Timestamp) -> pd.Series:
    values: dict[pd.Timestamp, float] = {}
    columns = returns.columns
    start_position = returns.index.searchsorted(start, side="left")
    for position in range(start_position, len(returns.index)):
        sample = returns.iloc[max(0, position - window + 1):position + 1][columns]
        corr = sample.corr(min_periods=20).to_numpy()
        upper = corr[np.triu_indices_from(corr, k=1)]
        valid = upper[np.isfinite(upper)]
        values[returns.index[position]] = float(valid.mean()) if valid.size else np.nan
    return pd.Series(values, name="correlation")


def build_features_from_panels(close: pd.DataFrame, returns: pd.DataFrame, volatility_window: int, momentum_window: int, analysis_start: str, output_start: str | None = None) -> pd.DataFrame:
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


def build_market_features(series: list[AssetSeries], volatility_window: int, momentum_window: int, analysis_start: str, output_start: str | None = None) -> pd.DataFrame:
    close, returns = build_price_panels(series)
    return build_features_from_panels(close, returns, volatility_window, momentum_window, analysis_start, output_start)
