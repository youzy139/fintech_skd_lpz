from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from market_core.models.features import FEATURE_COLUMNS

LEGACY_IDENTITY = "local-cluster-v1"
REGIME_IDENTITY = "centroid-alignment-v1"


class WalkForwardRegimeModel:
    def __init__(self, minimum_history: int, training_window: int, refit_interval: int, cluster_count: int, random_seed: int, regime_identity: str = REGIME_IDENTITY):
        if regime_identity not in {LEGACY_IDENTITY, REGIME_IDENTITY}:
            raise ValueError("不支持的状态身份算法版本")
        self.minimum_history = minimum_history
        self.training_window = training_window
        self.refit_interval = refit_interval
        self.cluster_count = cluster_count
        self.random_seed = random_seed
        self.regime_identity = regime_identity

    def _fit(self, train: pd.DataFrame):
        scaler = StandardScaler().fit(train[FEATURE_COLUMNS])
        transformed = scaler.transform(train[FEATURE_COLUMNS])
        pca = PCA(n_components=min(3, len(FEATURE_COLUMNS)), random_state=self.random_seed).fit(transformed)
        reduced = pca.transform(transformed)
        cluster = KMeans(n_clusters=self.cluster_count, random_state=self.random_seed, n_init=10).fit(reduced)
        return scaler, pca, cluster

    @staticmethod
    def _label(cluster_id: int, center: np.ndarray) -> str:
        return_value, volatility, momentum, correlation = center
        if volatility > 0.55 and return_value < 0:
            label = "高波动避险"
        elif momentum > 0.35 and return_value >= 0:
            label = "趋势上涨"
        elif momentum < -0.35 or return_value < -0.45:
            label = "下跌承压"
        elif correlation > 0.6:
            label = "联动震荡"
        else:
            label = "震荡平衡"
        return f"{label} · C{cluster_id}"

    def predict(self, features: pd.DataFrame) -> list[dict]:
        if len(features) < self.minimum_history:
            raise ValueError(f"状态识别至少需要 {self.minimum_history} 个有效特征日")
        session = WalkForwardRegimeSession(self)
        results = []
        for index in range(self.minimum_history, len(features)):
            state = session.predict_latest(features.iloc[:index + 1])
            if state is not None:
                results.append(state)
        return results


class WalkForwardRegimeSession:
    def __init__(self, model: WalkForwardRegimeModel):
        self.model = model
        self.fitted = None
        self.centers: np.ndarray | None = None
        self.raw_centers: np.ndarray | None = None
        self.regime_ids: np.ndarray | None = None
        self.trained_through: pd.Timestamp | None = None
        self.last_index = -1

    def _align_centers(self, fitted, centers: np.ndarray) -> np.ndarray:
        raw_centers = fitted[0].inverse_transform(centers)
        if self.raw_centers is None:
            regime_ids = np.arange(len(centers))
        else:
            # Both sets use original feature units and the previous training scale.
            # Sort columns first so exact cost ties do not depend on new local IDs.
            order = sorted(range(len(centers)), key=lambda index: tuple(raw_centers[index]))
            previous_order = np.argsort(self.regime_ids)
            differences = (self.raw_centers[previous_order, None, :] - raw_centers[order][None, :, :]) / self.fitted[0].scale_
            costs = np.sum(differences ** 2, axis=2)
            previous, current = linear_sum_assignment(costs)
            regime_ids = np.empty(len(centers), dtype=int)
            regime_ids[np.asarray(order)[current]] = self.regime_ids[previous_order[previous]]
        self.raw_centers = raw_centers
        return regime_ids

    def predict_latest(self, features: pd.DataFrame) -> dict | None:
        index = len(features) - 1
        if self.last_index >= 0 and index != self.last_index + 1:
            raise ValueError("回放状态模型必须按连续特征日依次推进")
        if index < self.model.minimum_history:
            self.last_index = index
            return None
        if self.fitted is None or (index - self.model.minimum_history) % self.model.refit_interval == 0:
            train = features.iloc[max(0, index - self.model.training_window):index]
            fitted = self.model._fit(train)
            centers = fitted[1].inverse_transform(fitted[2].cluster_centers_)
            if self.model.regime_identity == REGIME_IDENTITY:
                self.regime_ids = self._align_centers(fitted, centers)
            self.fitted = fitted
            self.centers = centers
            self.trained_through = features.index[index - 1]
        scaler, pca, cluster = self.fitted
        row = features.iloc[index]
        scaled = scaler.transform(row[FEATURE_COLUMNS].to_frame().T)
        reduced = pca.transform(scaled)
        distances = np.linalg.norm(reduced - cluster.cluster_centers_, axis=1)
        cluster_id = int(np.argmin(distances))
        regime_id = int(self.regime_ids[cluster_id]) if self.regime_ids is not None else cluster_id
        weights = np.exp(-(distances ** 2) / 2)
        confidence = float(weights[cluster_id] / weights.sum())
        contributions = sorted(
            ({"feature": name, "value": float(row[name]), "standardized": float(scaled[0][position])} for position, name in enumerate(FEATURE_COLUMNS)),
            key=lambda item: abs(item["standardized"]),
            reverse=True,
        )
        self.last_index = index
        state = {
            "date": features.index[index].strftime("%Y-%m-%d"),
            "cluster": cluster_id,
            "label": self.model._label(regime_id, self.centers[cluster_id]),
            "confidence": confidence,
            "model_version": f"walk-forward-{self.trained_through:%Y%m%d}",
            "trained_through": self.trained_through.strftime("%Y-%m-%d"),
            "features": {name: float(row[name]) for name in FEATURE_COLUMNS + ["trend", "sample_count"]},
            "contributions": contributions,
        }
        if self.model.regime_identity == REGIME_IDENTITY:
            state.update({
                "regime_id": regime_id,
                "regime_identity": REGIME_IDENTITY,
                "model_version": f"walk-forward-aligned-v1-{self.trained_through:%Y%m%d}",
            })
        return state
