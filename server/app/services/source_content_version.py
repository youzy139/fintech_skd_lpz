from __future__ import annotations

import hashlib
from typing import Any

from market_core.domain.source_quality import canonical_record


class SourceContentDigest:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    def update(self, record_index: int, event_date: str | None, title: str, payload: dict[str, Any]) -> None:
        canonical = canonical_record(event_date, title, payload)
        self._digest.update(str(record_index).encode("ascii") + b"\x00")
        self._digest.update(len(canonical).to_bytes(8, "big"))
        self._digest.update(canonical)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()
