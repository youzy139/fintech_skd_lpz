from __future__ import annotations

import json
from typing import Any


def canonical_record(event_date: str | None, title: str, payload: dict[str, Any]) -> bytes:
    return json.dumps(
        [event_date, title, payload], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
