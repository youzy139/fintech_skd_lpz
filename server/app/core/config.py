from __future__ import annotations

import json
import os
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
    kafka: dict[str, Any]
    flink: dict[str, Any]
    cors_origins: list[str]


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or SERVER_ROOT / "config.json"
    if not config_path.is_file():
        config_path = SERVER_ROOT / "config.example.json"
    with config_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    base = config_path.parent
    kafka = raw.get("kafka", {
        "enabled": False,
        "bootstrap_servers": "127.0.0.1:9092",
        "topic": "marketlens.replay.days.v1",
        "topic_partitions": 1,
        "consumer_max_retries": 3,
        "retry_backoff_ms": 200,
    })
    kafka["enabled"] = os.getenv("KAFKA_ENABLED", str(kafka["enabled"])).lower() == "true"
    kafka["bootstrap_servers"] = os.getenv("KAFKA_BOOTSTRAP_SERVERS", kafka["bootstrap_servers"])
    kafka["topic"] = os.getenv("KAFKA_TOPIC", kafka["topic"])
    flink = raw.get("flink", {
        "enabled": False,
        "rest_url": "http://127.0.0.1:8081",
        "output_topic": "marketlens.features.days.v1",
        "late_topic": "marketlens.replay.late.v1",
        "checkpoint_interval_ms": 5000,
    })
    flink["enabled"] = os.getenv("FLINK_ENABLED", str(flink["enabled"])).lower() == "true"
    flink["rest_url"] = os.getenv("FLINK_REST_URL", flink["rest_url"])
    return AppConfig(
        data_root=(base / raw["data_root"]).resolve(),
        database_path=(base / raw["database_path"]).resolve(),
        model=raw["model"],
        alerts=raw["alerts"],
        replay=raw["replay"],
        kafka=kafka,
        flink=flink,
        cors_origins=raw["cors_origins"],
    )
