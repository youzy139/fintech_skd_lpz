from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from market_core.models.features import FEATURE_COLUMNS


class WalkForwardRegimeModel:
    def __init__(self, minimum_history: int, training_window: int, refit_interval: int, cluster_count: int, random_seed: int):
        self.minimum_history = minimum_history
        self.training_window = training_window
        self.refit_interval = refit_interval
        self.cluster_count = cluster_count
        self.random_seed = random_seed

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
        results: list[dict] = []
        fitted = None
        centers: np.ndarray | None = None
        trained_through: pd.Timestamp | None = None
        for index in range(self.minimum_history, len(features)):
            if fitted is None or (index - self.minimum_history) % self.refit_interval == 0:
                train = features.iloc[max(0, index - self.training_window):index]
                fitted = self._fit(train)
                centers = fitted[1].inverse_transform(fitted[2].cluster_centers_)
                trained_through = features.index[index - 1]
            scaler, pca, cluster = fitted
            row = features.iloc[index]
            scaled = scaler.transform(row[FEATURE_COLUMNS].to_frame().T)
            reduced = pca.transform(scaled)
            distances = np.linalg.norm(reduced - cluster.cluster_centers_, axis=1)
            cluster_id = int(np.argmin(distances))
            weights = np.exp(-(distances ** 2) / 2)
            confidence = float(weights[cluster_id] / weights.sum())
            contributions = sorted(
                ({"feature": name, "value": float(row[name]), "standardized": float(scaled[0][position])} for position, name in enumerate(FEATURE_COLUMNS)),
                key=lambda item: abs(item["standardized"]),
                reverse=True,
            )
            results.append(
                {
                    "date": features.index[index].strftime("%Y-%m-%d"),
                    "cluster": cluster_id,
                    "label": self._label(cluster_id, centers[cluster_id]),
                    "confidence": confidence,
                    "model_version": f"walk-forward-{trained_through:%Y%m%d}",
                    "trained_through": trained_through.strftime("%Y-%m-%d"),
                    "features": {name: float(row[name]) for name in FEATURE_COLUMNS + ["trend", "sample_count"]},
                    "contributions": contributions,
                }
            )
        return results
