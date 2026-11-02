from __future__ import annotations

from typing import Any


def response_headers(headers: Any) -> dict[str, str]:
    forwarded = {"Content-Type": headers.get("Content-Type", "application/json")}
    for name in ("Retry-After", "WWW-Authenticate", "Allow"):
        value = headers.get(name)
        if value is not None:
            forwarded[name] = value
    return forwarded
