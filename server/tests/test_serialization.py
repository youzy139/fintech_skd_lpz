from __future__ import annotations

import json

from app.core.serialization import json_compatible


def test_non_finite_numbers_become_null_without_changing_other_values():
    value = {
        "finite": 1.25,
        "integer": 2,
        "nested": (float("nan"), float("inf"), float("-inf")),
        "text": "NaN remains text",
    }

    converted = json_compatible(value)

    assert converted == {
        "finite": 1.25,
        "integer": 2,
        "nested": [None, None, None],
        "text": "NaN remains text",
    }
    assert value["nested"][0] != value["nested"][0]
    json.dumps(converted, allow_nan=False)
