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
    mysql: dict[str, Any]
    minio: dict[str, Any]
    clickhouse: dict[str, Any]
    redis: dict[str, Any]
    storage_mode: str
    cors_origins: list[str]


def load_config(path: Path | None = None) -> AppConfig:
    configured_path = os.getenv("MARKETLENS_CONFIG")
    config_path = path or (Path(configured_path) if configured_path else SERVER_ROOT / "config.json")
    if not config_path.is_file():
        config_path = SERVER_ROOT / "config.example.json"
    with config_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    base = config_path.parent

    def enabled(name: str, settings: dict[str, Any]) -> None:
        settings["enabled"] = os.getenv(f"{name}_ENABLED", str(settings["enabled"])).lower() == "true"

    def override(name: str, settings: dict[str, Any], *keys: str) -> None:
        for key in keys:
            environment_key = f"{name}_{key.upper()}"
            settings[key] = os.getenv(environment_key, str(settings[key]))

    kafka = raw.get("kafka", {
        "enabled": False,
        "bootstrap_servers": "127.0.0.1:9092",
        "topic": "marketlens.replay.days.v1",
        "topic_partitions": 1,
        "consumer_max_retries": 3,
        "retry_backoff_ms": 200,
    })
    enabled("KAFKA", kafka)
    override("KAFKA", kafka, "bootstrap_servers", "topic")
    flink = raw.get("flink", {
        "enabled": False,
        "rest_url": "http://127.0.0.1:8081",
        "output_topic": "marketlens.features.days.v1",
        "late_topic": "marketlens.replay.late.v1",
        "checkpoint_interval_ms": 5000,
        "checkpoint_dir": "file:///tmp/marketlens-flink-checkpoints",
        "request_timeout_seconds": 10,
        "job_start_timeout_ms": 90000,
        "job_stop_timeout_ms": 60000,
    })
    enabled("FLINK", flink)
    override("FLINK", flink, "rest_url", "output_topic", "late_topic", "checkpoint_interval_ms", "checkpoint_dir", "request_timeout_seconds", "job_start_timeout_ms", "job_stop_timeout_ms")
    mysql = raw.get("mysql", {"enabled": False, "host": "127.0.0.1", "port": 3307, "database": "marketlens", "user": "root", "password": ""})
    enabled("MYSQL", mysql)
    override("MYSQL", mysql, "host", "port", "database", "user")
    mysql["password"] = os.getenv("MYSQL_PASSWORD", mysql["password"])
    minio = raw.get("minio", {"enabled": False, "endpoint": "127.0.0.1:9000", "access_key": "", "secret_key": "", "bucket": "marketlens-raw", "secure": False})
    enabled("MINIO", minio)
    override("MINIO", minio, "endpoint", "bucket")
    minio["access_key"] = os.getenv("MINIO_ACCESS_KEY", minio["access_key"])
    minio["secret_key"] = os.getenv("MINIO_SECRET_KEY", minio["secret_key"])
    clickhouse = raw.get("clickhouse", {"enabled": False, "host": "127.0.0.1", "port": 8123, "database": "marketlens", "username": "default", "password": "", "secure": False})
    enabled("CLICKHOUSE", clickhouse)
    override("CLICKHOUSE", clickhouse, "host", "port", "database", "username")
    clickhouse["password"] = os.getenv("CLICKHOUSE_PASSWORD", clickhouse["password"])
    redis = raw.get("redis", {"enabled": False, "host": "127.0.0.1", "port": 6379, "db": 0, "password": "", "ttl_seconds": 60, "namespace": "marketlens:catalog:v1"})
    enabled("REDIS", redis)
    override("REDIS", redis, "host", "port", "db", "ttl_seconds", "namespace")
    redis["password"] = os.getenv("REDIS_PASSWORD", redis["password"])
    storage_mode = os.getenv("STORAGE_MODE", raw.get("storage_mode", "local"))
    if storage_mode not in {"local", "distributed"}:
        raise ValueError("STORAGE_MODE 必须为 local 或 distributed")
    if storage_mode == "distributed" and not clickhouse["enabled"]:
        raise ValueError("distributed 模式必须显式启用 ClickHouse")
    data_root = Path(os.getenv("DATA_ROOT", raw["data_root"]))
    database_path = Path(os.getenv("DATABASE_PATH", raw["database_path"]))
    cors_origins = os.getenv("CORS_ORIGINS", ",".join(raw["cors_origins"])).split(",")
    return AppConfig(
        data_root=(base / data_root).resolve(),
        database_path=(base / database_path).resolve(),
        model=raw["model"],
        alerts=raw["alerts"],
        replay=raw["replay"],
        kafka=kafka,
        flink=flink,
        mysql=mysql,
        minio=minio,
        clickhouse=clickhouse,
        redis=redis,
        storage_mode=storage_mode,
        cors_origins=[origin.strip() for origin in cors_origins if origin.strip()],
    )
