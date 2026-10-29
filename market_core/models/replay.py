from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from market_core.domain.market import AssetSeries
from market_core.domain.replay import ReplayDayInput, ReplayDayResult
from market_core.models.alerts import generate_alerts
from market_core.models.features import build_market_features
from market_core.models.regime import WalkForwardRegimeModel, WalkForwardRegimeSession


class HistoricalMarketReplay:
    def __init__(self, series: list[AssetSeries], model_settings: dict[str, Any], alert_settings: dict[str, Any], start: date):
        self.model_settings = dict(model_settings)
        self.alert_settings = dict(alert_settings)
        self.last_event_date: date | None = None
        self.history = [
            AssetSeries(item.meta, item.frame.loc[item.frame["date"] < pd.Timestamp(start)].copy(), item.duplicate_dates, item.invalid_rows)
            for item in series
        ]
        self.by_code = {item.meta.code: item for item in self.history}
        self.features = self._calculate_features()
        model = WalkForwardRegimeModel(
            model_settings["minimum_history"],
            model_settings["training_window"],
            model_settings["refit_interval"],
            model_settings["cluster_count"],
            model_settings["random_seed"],
        )
        self.model_session = WalkForwardRegimeSession(model)
        self.states: list[dict] = []
        for index in range(model.minimum_history, len(self.features)):
            state = self.model_session.predict_latest(self.features.iloc[:index + 1])
            if state is not None:
                self.states.append(state)

    def _calculate_features(self, output_start: str | None = None) -> pd.DataFrame:
        return build_market_features(
            self.history,
            self.model_settings["volatility_window"],
            self.model_settings["momentum_window"],
            self.model_settings["analysis_start"],
            output_start,
        )

    def advance(self, batch: ReplayDayInput) -> ReplayDayResult:
        event_day = pd.Timestamp(batch.event_date)
        if self.last_event_date is not None and batch.event_date <= self.last_event_date:
            raise ValueError("回放输入必须按事件日期递增")
        if any(item.event_date != batch.event_date for item in batch.observations):
            raise ValueError("输入批次包含其他事件日期的数据")
        for observation in batch.observations:
            target = self.by_code.get(observation.code)
            if target is None:
                raise ValueError(f"未知资产 {observation.code}")
            if (target.frame["date"] == event_day).any():
                raise ValueError(f"资产 {observation.code} 在 {batch.event_date} 存在重复输入")
            addition = pd.DataFrame({"date": [event_day], "value": [observation.value]})
            target.frame = pd.concat([target.frame, addition], ignore_index=True)
        self.last_event_date = batch.event_date

        latest = self._calculate_features(batch.event_date.isoformat())
        previous_length = len(self.features)
        if not latest.empty:
            self.features = pd.concat([self.features, latest])
        state = None
        if len(self.features) > previous_length:
            state = self.model_session.predict_latest(self.features)
            if state is not None:
                self.states.append(state)
        alerts = generate_alerts(self.states, self.alert_settings["volatility_quantile"], self.alert_settings["correlation_quantile"])
        daily_alerts = tuple(asdict(item) for item in alerts if item.date == batch.event_date.isoformat())
        observed_dates = [item.frame["date"].min() for item in self.history if not item.frame.empty]
        return ReplayDayResult(
            event_time=batch.event_date.isoformat(),
            replay_time=datetime.now(timezone.utc).isoformat(),
            input_start=min(observed_dates).strftime("%Y-%m-%d"),
            input_end=batch.event_date.isoformat(),
            input_records=len(batch.observations),
            observed_assets=tuple(sorted(item.code for item in batch.observations)),
            features={name: float(value) for name, value in latest.iloc[0].items()} if not latest.empty else {},
            state=state,
            alerts=daily_alerts,
            model_version=state["model_version"] if state else "walk-forward-warm-up",
        )
