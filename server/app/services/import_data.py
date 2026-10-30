from __future__ import annotations

import argparse
import time

from app.core.config import load_config
from app.services.catalog import CatalogStore
from market_core.ingestion.sources import discover_sources


def import_files(store: CatalogStore, sources: list) -> dict[str, int]:
    started = time.monotonic()
    counts = {"imported": 0, "skipped": 0, "failed": 0}
    print(f"发现 {len(sources)} 个输入文件", flush=True)
    for index, source in enumerate(sources, 1):
        if store.is_unchanged(source):
            counts["skipped"] += 1
            continue
        file_started = time.monotonic()
        try:
            result = store.import_file(source)
            counts["imported"] += 1
            print(f"[{index}/{len(sources)}] {source.path}: {result['record_count']} 条，{time.monotonic() - file_started:.1f}s", flush=True)
        except Exception as error:
            counts["failed"] += 1
            print(f"[{index}/{len(sources)}] {source.path}: 失败 {error}", flush=True)
    counts["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(f"完成：新导入 {counts['imported']}，跳过 {counts['skipped']}，失败 {counts['failed']}，耗时 {counts['elapsed_seconds']:.1f}s", flush=True)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-stats", action="store_true")
    args = parser.parse_args()
    config = load_config()
    store = CatalogStore(config.database_path)
    try:
        if args.rebuild_stats:
            started = time.monotonic()
            result = store.rebuild_statistics()
            print(f"统计回填完成：{result['sources']} 个文件，{result['records']} 条记录，耗时 {time.monotonic() - started:.1f}s", flush=True)
            return 0
        result = import_files(store, discover_sources(config.data_root))
        print(store.summary(), flush=True)
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
