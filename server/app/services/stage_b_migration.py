from __future__ import annotations

import argparse

from app.core.config import load_config
from app.services.catalog import CatalogStore
from app.services.mysql_metadata import MySQLMetadataStore
from app.services.object_archive import ObjectArchive
from market_core.ingestion.sources import discover_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 SQLite 元数据到 MySQL，并将原始文件归档到 MinIO")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须大于 0")
    config = load_config()
    if not config.mysql["enabled"]:
        parser.error("请通过 MYSQL_ENABLED=true 或私有配置启用 MySQL")
    if not args.metadata_only and not config.minio["enabled"]:
        parser.error("对象归档需要 MINIO_ENABLED=true；仅迁移元数据可使用 --metadata-only")
    catalog = CatalogStore(config.database_path)
    metadata = MySQLMetadataStore(config.mysql)
    try:
        metadata.initialize()
        if not args.verify_only:
            copied = metadata.migrate_from(catalog)
            print(f"MySQL 元数据迁移：{copied['files']} 个文件，{copied['import_batches']} 个导入批次", flush=True)
        differences = metadata.verify_against(catalog)
        if differences:
            for difference in differences:
                print(difference)
            return 1
        print("MySQL 与 SQLite 元数据核对通过", flush=True)
        if args.metadata_only:
            return 0
        sources = discover_sources(config.data_root)
        if args.source_id:
            selected = set(args.source_id)
            sources = [source for source in sources if source.id in selected]
            missing = selected - {source.id for source in sources}
            if missing:
                parser.error(f"来源 ID 不存在：{', '.join(sorted(missing))}")
        if args.limit is not None:
            sources = sources[:args.limit]
        archive = ObjectArchive.from_config(config.minio)
        uploaded = 0
        reused = 0
        verified = 0
        for index, source in enumerate(sources, 1):
            if args.verify_only:
                object_metadata = metadata.object_for_source(source.id)
                if not object_metadata:
                    raise RuntimeError(f"缺少对象元数据：{source.id} {source.path}")
            else:
                object_metadata = archive.archive(source)
                if object_metadata["uploaded"]:
                    uploaded += 1
                else:
                    reused += 1
                metadata.register_object(
                    source.id,
                    object_metadata["bucket"],
                    object_metadata["key"],
                    object_metadata["sha256"],
                    object_metadata["size"],
                    object_metadata["etag"],
                    object_metadata["version_id"],
                )
            archive.verify(source, object_metadata)
            verified += 1
            if index == 1 or index % 100 == 0 or index == len(sources):
                print(f"对象进度 {index}/{len(sources)}：已回读校验 {verified}", flush=True)
        print(f"阶段 B 完成：新上传 {uploaded}，复用 {reused}，回读校验 {verified}，对象元数据 {metadata.object_count()}", flush=True)
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main())
