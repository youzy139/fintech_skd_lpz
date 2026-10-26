from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppConfig:
    data_root: Path
    database_path: Path
    model: dict[str, Any]
    alerts: dict[str, Any]
    replay: dict[str, Any]
    cors_origins: list[str]


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or SERVER_ROOT / "config.json"
    if not config_path.is_file():
        config_path = SERVER_ROOT / "config.example.json"
    with config_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    base = config_path.parent
    return AppConfig(
        data_root=(base / raw["data_root"]).resolve(),
        database_path=(base / raw["database_path"]).resolve(),
        model=raw["model"],
        alerts=raw["alerts"],
        replay=raw["replay"],
        cors_origins=raw["cors_origins"],
    )
