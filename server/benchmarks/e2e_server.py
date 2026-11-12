from __future__ import annotations

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))


def prepare(root: Path):
    data_root = root / "data"
    assets = data_root / "目标资产价格变量"
    assets.mkdir(parents=True)
    dates = pd.bdate_range("2020-01-01", periods=1000)
    with (assets / "代码对照.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["名称", "Wind代码", "大类", "字段", "交易日历", "起始", "结束", "条数", "状态"])
        for index, name in enumerate(("合成资产A", "合成资产B", "合成资产C")):
            writer.writerow([name, f"SYNTHETIC.{chr(65 + index)}", "合成测试", "close", "工作日", dates[0].date().isoformat(), dates[-1].date().isoformat(), len(dates), "ok"])
    for index, name in enumerate(("合成资产A", "合成资产B", "合成资产C")):
        with (assets / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "close"])
            for day_index, day in enumerate(dates):
                value = 100 + index * 25 + day_index * (0.015 + index * 0.005) + math.sin(day_index / (13 + index * 4)) * (2 + index)
                writer.writerow([day.date().isoformat(), round(value, 6)])
    example = json.loads((ROOT / "server" / "config.example.json").read_text(encoding="utf-8"))
    for name in ("kafka", "flink", "mysql", "minio", "clickhouse", "redis"):
        example[name]["enabled"] = False
    config_path = root / "config.json"
    config_path.write_text(json.dumps(example), encoding="utf-8")
    os.environ.update({
        "MARKETLENS_CONFIG": str(config_path),
        "DATA_ROOT": str(data_root),
        "DATABASE_PATH": str(root / "market.db"),
        "AUTH_DATABASE_PATH": str(root / "auth.db"),
        "AUTH_ENABLED": "true",
        "AUTH_SERVICE_NAME": "backend",
        "AUTH_SESSION_SECONDS": "3600",
        "AUTH_COOKIE_SECURE": "false",
        "CORS_ORIGINS": "http://localhost:5174,http://127.0.0.1:5174",
        "RATE_LIMIT_MODE": "local",
        "STORAGE_MODE": "local",
        "FEATURE_SERVICE_URL": "",
        "DATA_SERVICE_URL": "",
        "ALERT_SERVICE_URL": "",
    })
    from app.services.catalog import CatalogStore
    from market_core.domain.sources import SourceFile

    social = data_root / "科技.csv"
    with social.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows([["created_at_twitter", "text", "optional"], ["2020-01-01", "合成目录样本", ""], ["", "无日期样本", ""], ["invalid", "", ""]])
    catalog = CatalogStore(root / "market.db")
    try:
        catalog.import_file(SourceFile.create(data_root, social, "social"))
    finally:
        catalog.close()


def main():
    import uvicorn

    with tempfile.TemporaryDirectory(prefix="marketlens-e2e-") as directory:
        prepare(Path(directory))
        from app.core.auth import auth_store

        store = auth_store()
        with store.connect() as db:
            db.execute("UPDATE auth_meta SET value='e2e-only-setup-code' WHERE name='bootstrap'")
        uvicorn.run("app.main:app", app_dir=str(ROOT / "server"), host="127.0.0.1", port=18000, log_level="warning")


if __name__ == "__main__":
    main()
