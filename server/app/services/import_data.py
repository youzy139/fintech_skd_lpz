from __future__ import annotations

import argparse
import time

from app.core.config import load_config
from app.services.catalog import CatalogStore
from market_core.ingestion.sources import discover_sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-stats", action="store_true")
    args = parser.parse_args()
    config = load_config()
    store = CatalogStore(config.database_path)
    started = time.monotonic()
    try:
        if args.rebuild_stats:
            result = store.rebuild_statistics()
            print(f"统计回填完成：{result['sources']} 个文件，{result['records']} 条记录，耗时 {time.monotonic() - started:.1f}s", flush=True)
            return 0
        sources = discover_sources(config.data_root)
        imported = 0
        skipped = 0
        failed = 0
        print(f"发现 {len(sources)} 个输入文件", flush=True)
        for index, source in enumerate(sources, 1):
            if store.is_unchanged(source):
                skipped += 1
                continue
            file_started = time.monotonic()
            try:
                result = store.import_file(source)
                imported += 1
                print(f"[{index}/{len(sources)}] {source.path}: {result['record_count']} 条，{time.monotonic() - file_started:.1f}s", flush=True)
            except Exception as error:
                failed += 1
                print(f"[{index}/{len(sources)}] {source.path}: 失败 {error}", flush=True)
        print(f"完成：新导入 {imported}，跳过 {skipped}，失败 {failed}，耗时 {time.monotonic() - started:.1f}s", flush=True)
        print(store.summary(), flush=True)
        return 1 if failed else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
