from __future__ import annotations

from types import SimpleNamespace
from itertools import permutations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from market_core.models.alerts import generate_alerts
from market_core.models.regime import LEGACY_IDENTITY, REGIME_IDENTITY, WalkForwardRegimeModel, WalkForwardRegimeSession


class IdentityTransform:
    scale_ = np.ones(4)

    def transform(self, values):
        return np.asarray(values)

    def inverse_transform(self, values):
        return np.asarray(values)


def controlled_states(centers, observations, identity=REGIME_IDENTITY):
    model = WalkForwardRegimeModel(2, 10, 1, len(centers[0]), 42, identity)
    fits = iter(centers)
    model._fit = lambda train: (IdentityTransform(), IdentityTransform(), SimpleNamespace(cluster_centers_=np.asarray(next(fits))))
    rows = [observations[0], observations[0], *observations]
    frame = pd.DataFrame(rows, columns=["market_return", "volatility", "momentum", "correlation"], index=pd.date_range("2024-01-01", periods=len(rows)))
    frame["trend"] = 0.0
    frame["sample_count"] = 5
    return model.predict(frame)


def test_refit_permutation_does_not_create_a_regime_change():
    a, b = [0.1, 0.1, 0.0, 0.1], [0.2, 0.2, 0.1, 0.2]
    states = controlled_states([[a, b], [b, a]], [a, a])
    assert not [item for item in generate_alerts(states, 0.9, 0.9) if item.rule == "REGIME_CHANGE"]
    assert [state["cluster"] for state in states] == [0, 1]
    assert [state["regime_id"] for state in states] == [0, 0]
    assert states[0]["label"] == states[1]["label"]


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_all_refit_permutations_preserve_distinct_same_semantic_clusters(order):
    centers = [[0.1, 0.1, 0.0, 0.1], [0.2, 0.2, 0.1, 0.2], [0.3, 0.3, 0.2, 0.3]]
    permuted = [centers[index] for index in order]
    states = controlled_states([centers, permuted, permuted, permuted], [centers[0], centers[0], centers[1], centers[2]])
    assert [state["regime_id"] for state in states] == [0, 0, 1, 2]
    assert [state["date"] for state in states[2:]] == [alert.date for alert in generate_alerts(states, 0.9, 0.9)]


def test_semantic_change_of_the_same_matched_cluster_still_alerts():
    a, b = [0.1, 0.1, 0.34, 0.1], [2.0, 0.2, 0.2, 0.2]
    changed = [0.1, 0.1, 0.36, 0.1]
    states = controlled_states([[a, b], [b, changed]], [a, changed])
    assert [state["regime_id"] for state in states] == [0, 0]
    alerts = generate_alerts(states, 0.9, 0.9)
    assert len(alerts) == 1
    assert alerts[0].rule == "REGIME_CHANGE"
    assert "震荡平衡" in alerts[0].evidence and "趋势上涨" in alerts[0].evidence


def test_matching_uses_original_units_and_one_common_scale():
    session = WalkForwardRegimeSession(WalkForwardRegimeModel(2, 10, 1, 2, 42))
    previous_scaler = StandardScaler().fit([[0, 0, 0, 0], [2, 4, 6, 8]])
    previous_raw = np.array([[0.1, 0.1, 0.1, 0.1], [1.5, 2.5, 4.5, 6.5]])
    previous = (previous_scaler, IdentityTransform(), None)
    session.regime_ids = session._align_centers(previous, previous_scaler.transform(previous_raw))
    session.fitted = previous
    new_scaler = StandardScaler().fit([[10, 20, 30, 40], [11, 23, 35, 47]])
    permuted = previous_raw[::-1] + 0.01
    matched = session._align_centers((new_scaler, IdentityTransform(), None), new_scaler.transform(permuted))
    assert matched.tolist() == [1, 0]


def test_matching_minimizes_global_cost_instead_of_greedy_nearest():
    a, b = [0, 0, 0, 0], [3, 0, 0, 0]
    next_a, next_b = [2, 0, 0, 0], [4, 0, 0, 0]
    states = controlled_states([[a, b], [next_a, next_b]], [a, next_a])
    assert [state["regime_id"] for state in states] == [0, 0]


def test_equal_matching_cost_has_a_permutation_independent_tie_break():
    previous = [[0, -1, 0, 0], [0, 1, 0, 0]]
    left, right = [-1, 0, 0, 0], [1, 0, 0, 0]
    first = controlled_states([previous, [left, right]], [previous[0], left])
    second = controlled_states([previous, [right, left]], [previous[0], left])
    assert first[-1]["regime_id"] == second[-1]["regime_id"]


def test_legacy_mode_keeps_original_labels_versions_and_alerts():
    a, b = [0.1, 0.1, 0.0, 0.1], [0.2, 0.2, 0.1, 0.2]
    states = controlled_states([[a, b], [b, a]], [a, a], LEGACY_IDENTITY)
    assert [state["label"] for state in states] == ["震荡平衡 · C0", "震荡平衡 · C1"]
    assert states[0]["model_version"] == "walk-forward-20240102"
    assert all("regime_id" not in state and "regime_identity" not in state for state in states)
    assert len(generate_alerts(states, 0.9, 0.9)) == 1


def test_unknown_identity_version_is_rejected():
    with pytest.raises(ValueError, match="身份算法版本"):
        WalkForwardRegimeModel(2, 10, 1, 2, 42, "future")
