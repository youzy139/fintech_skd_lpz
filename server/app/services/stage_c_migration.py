from __future__ import annotations

import argparse

from app.core.config import load_config
from app.services.catalog import CatalogStore
from app.services.clickhouse_migration import ClickHouseMigrator
from app.services.clickhouse_store import ClickHouseCatalogStore


def main() -> int:
    parser = argparse.ArgumentParser(description="将 SQLite 目录与市场结果迁移到 ClickHouse，并执行双读对照")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--query-limit", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.query_limit <= 100:
        parser.error("--query-limit 必须在 1 到 100 之间")
    config = load_config()
    if not config.clickhouse["enabled"]:
        parser.error("请通过 CLICKHOUSE_ENABLED=true 或私有配置启用 ClickHouse")
    catalog = CatalogStore(config.database_path)
    store = ClickHouseCatalogStore(config.clickhouse)
    migrator = ClickHouseMigrator(store, config.alerts)
    try:
        store.initialize()
        if not args.verify_only:
            counts = migrator.migrate(catalog, reset=True)
            print(f"ClickHouse 全量重建完成：{counts}", flush=True)
        differences = [*migrator.verify_counts(catalog), *migrator.verify_queries(catalog, args.query_limit)]
        if differences:
            print(f"ClickHouse 双读核对失败：{len(differences)} 处差异")
            for difference in differences[:20]:
                print(difference)
            if len(differences) > 20:
                print(f"另有 {len(differences) - 20} 处差异未显示")
            return 1
        print("ClickHouse 与 SQLite 计数及典型查询核对通过；应用主读路径未切换", flush=True)
        return 0
    finally:
        catalog.close()
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
