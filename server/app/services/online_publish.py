from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable

from app.core.config import load_config
from app.services.catalog import CatalogStore
from app.services.clickhouse_migration import FILE_COLUMNS, RECORD_COLUMNS, TAG_COLUMNS, ClickHouseMigrator
from app.services.clickhouse_store import ClickHouseCatalogStore, iso_date
from app.services.import_data import import_files
from app.services.market import MarketService
from app.services.mysql_metadata import MySQLMetadataStore
from app.services.object_archive import ObjectArchive
from market_core.domain.sources import SourceFile
from market_core.ingestion.sources import discover_sources


def _digest(value: object) -> bytes:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).digest()


class OnlinePublisher:
    def __init__(
        self,
        catalog: CatalogStore,
        store: ClickHouseCatalogStore,
        metadata: MySQLMetadataStore | None = None,
        archive: ObjectArchive | None = None,
        transformation_version: str = "sqlite-online-v1",
        rule_settings: dict[str, Any] | None = None,
    ):
        self.catalog = catalog
        self.store = store
        self.metadata = metadata
        self.archive = archive
        self.migrator = ClickHouseMigrator(store, rule_settings or {"volatility_quantile": 0.9, "correlation_quantile": 0.9}, transformation_version)

    def changed_sources(self, sources: Iterable[SourceFile]) -> list[SourceFile]:
        published = self.store.published_versions()
        return [source for source in sources if published.get(source.id, (None, None))[:2] != (source.size, source.mtime_ns)]

    def publish(self, sources: list[SourceFile], only_changed: bool = True) -> dict[str, Any]:
        self.store.initialize()
        if self.metadata:
            self.metadata.initialize()
            self.metadata.migrate_from(self.catalog)
        published = self.store.published_versions()
        selected = self.changed_sources(sources) if only_changed else sources
        counts = {"selected": len(selected), "published": 0, "skipped": len(sources) - len(selected), "objects_verified": 0, "records": 0}
        for source in selected:
            if self.archive:
                if not self.metadata:
                    raise ValueError("对象归档必须同时登记 MySQL 元数据")
                archived = self.archive.archive(source)
                self.archive.verify(source, archived)
                self.metadata.register_object(source.id, archived["bucket"], archived["key"], archived["sha256"], archived["size"], archived["etag"], archived["version_id"])
                counts["objects_verified"] += 1
            generation = max(source.mtime_ns, 1, published.get(source.id, (0, 0, 0))[2] + 1)
            self.store.record_run(source.id, generation, "staging")
            try:
                self._stage(source, generation)
                self._verify_staged(source, generation)
                self.store.activate(source.id, generation, self._record_count(source.id))
            except Exception as error:
                self.store.record_run(source.id, generation, "failed", error=str(error)[:1000])
                raise
            counts["published"] += 1
            counts["records"] += self._record_count(source.id)
        counts["market"] = self.migrator.refresh_market(self.catalog)
        differences = [*self.migrator.verify_counts(self.catalog), *self.migrator.verify_queries(self.catalog)]
        if differences:
            raise RuntimeError("发布后的 SQLite/ClickHouse 对照失败：" + "；".join(differences[:10]))
        return counts

    def _source_row(self, source_id: str) -> tuple:
        row = self.catalog.connection.execute(
            "SELECT id, kind, path, size, mtime_ns, status, record_count, error_count, sheets_json, error, updated_at FROM source_files WHERE id = ? AND status = 'imported'",
            (source_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"来源尚未在 SQLite 成功导入：{source_id}")
        return row

    def _record_count(self, source_id: str) -> int:
        return int(self.catalog.connection.execute("SELECT record_count FROM source_files WHERE id = ?", (source_id,)).fetchone()[0])

    def _stage(self, source: SourceFile, generation: int) -> None:
        row = self._source_row(source.id)
        self.store.discard_staged(source.id, generation)
        self.store.insert("dwd_source_files", [(*row[:10], datetime.fromisoformat(row[10]), self.migrator.transformation_version, generation)], FILE_COLUMNS)
        batch = self.catalog.connection.execute("SELECT COALESCE(MAX(id), 0) FROM import_batches WHERE source_id = ?", (source.id,)).fetchone()[0]
        records = self.catalog.connection.execute("SELECT record_index, event_date, title, payload_json FROM source_records WHERE source_id = ? ORDER BY record_index", (source.id,))
        while rows := records.fetchmany(1000):
            self.store.insert("dwd_source_records", [(source.id, index, source.kind, source.path, batch, day, title, payload, self.migrator.transformation_version, generation) for index, day, title, payload in rows], RECORD_COLUMNS)
        tags = self.catalog.connection.execute("SELECT record_index, tag, event_date FROM source_record_tags WHERE source_id = ? ORDER BY record_index, tag", (source.id,))
        while rows := tags.fetchmany(5000):
            self.store.insert("dwd_source_record_tags", [(source.id, index, source.kind, tag, day, self.migrator.transformation_version, generation) for index, tag, day in rows], TAG_COLUMNS)
        statistics = (
            ("source_daily_stats", "dws_source_daily_stats", "source_id, event_date, record_count"),
            ("source_fields", "dws_source_fields", "source_id, name, field_position, non_null_count"),
            ("source_tag_stats", "dws_source_tag_stats", "source_id, kind, tag, record_count"),
        )
        for sqlite_table, clickhouse_table, columns in statistics:
            rows = self.catalog.connection.execute(f"SELECT {columns} FROM {sqlite_table} WHERE source_id = ?", (source.id,)).fetchall()
            self.store.insert(clickhouse_table, [(*values, self.migrator.transformation_version, generation) for values in rows], [*columns.split(", "), "transformation_version", "generation"])

    def _verify_staged(self, source: SourceFile, generation: int) -> None:
        parameters = {"source_id": source.id, "generation": generation}
        row = self._source_row(source.id)
        actual_file = self.store.client.query(
            "SELECT id, kind, path, size, mtime_ns, status, record_count, error_count, sheets_json, error FROM dwd_source_files WHERE id = {source_id:String} AND generation = {generation:UInt64}",
            parameters=parameters,
        ).result_rows
        if len(actual_file) != 1 or tuple(actual_file[0]) != tuple(row[:10]):
            raise ValueError(f"暂存文件元数据不一致：{source.id}")
        for sqlite_table, clickhouse_table in (
            ("source_records", "dwd_source_records"),
            ("source_record_tags", "dwd_source_record_tags"),
            ("source_daily_stats", "dws_source_daily_stats"),
            ("source_fields", "dws_source_fields"),
            ("source_tag_stats", "dws_source_tag_stats"),
        ):
            expected = self.catalog.connection.execute(f"SELECT COUNT(*) FROM {sqlite_table} WHERE source_id = ?", (source.id,)).fetchone()[0]
            actual = self.store.client.query(
                f"SELECT COUNT(*) FROM {clickhouse_table} WHERE source_id = {{source_id:String}} AND generation = {{generation:UInt64}}",
                parameters=parameters,
            ).result_rows[0][0]
            if expected != actual:
                raise ValueError(f"暂存计数不一致：{source.id} {clickhouse_table} {expected} != {actual}")
        self._verify_record_digest(source, generation)
        self._verify_tag_digest(source, generation)

    def _verify_record_digest(self, source: SourceFile, generation: int) -> None:
        expected = hashlib.sha256()
        rows = self.catalog.connection.execute("SELECT record_index, event_date, title, payload_json, kind FROM source_records WHERE source_id = ? ORDER BY record_index", (source.id,))
        while batch := rows.fetchmany(1000):
            for index, day, title, payload, kind in batch:
                expected.update(_digest([source.id, index, day, title, payload, kind]))
        actual = hashlib.sha256()
        with self.store.client.query_row_block_stream(
            "SELECT record_index, event_date, title, payload_json, kind FROM dwd_source_records WHERE source_id = {source_id:String} AND generation = {generation:UInt64} ORDER BY record_index",
            parameters={"source_id": source.id, "generation": generation},
        ) as stream:
            for block in stream:
                for index, day, title, payload, kind in block:
                    actual.update(_digest([source.id, index, iso_date(day), title, payload, kind]))
        if expected.digest() != actual.digest():
            raise ValueError(f"暂存记录内容摘要不一致：{source.id}")

    def _verify_tag_digest(self, source: SourceFile, generation: int) -> None:
        expected_rows = self.catalog.connection.execute("SELECT record_index, tag, event_date FROM source_record_tags WHERE source_id = ? ORDER BY record_index, tag", (source.id,)).fetchall()
        actual_rows = self.store.client.query(
            "SELECT record_index, tag, event_date FROM dwd_source_record_tags WHERE source_id = {source_id:String} AND generation = {generation:UInt64} ORDER BY record_index, tag",
            parameters={"source_id": source.id, "generation": generation},
        ).result_rows
        normalized = [(index, tag, iso_date(day)) for index, tag, day in actual_rows]
        if expected_rows != normalized:
            raise ValueError(f"暂存标签内容不一致：{source.id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="将 SQLite 已导入来源增量发布到 MySQL、MinIO 与 ClickHouse")
    parser.add_argument("--initialize", action="store_true", help="先导入变化的原始文件并重建本地模型快照")
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须大于 0")
    config = load_config()
    if not all((config.mysql["enabled"], config.minio["enabled"], config.clickhouse["enabled"])):
        parser.error("在线发布需要显式启用 MySQL、MinIO 和 ClickHouse")
    sources = discover_sources(config.data_root)
    if args.source_id:
        selected = set(args.source_id)
        sources = [source for source in sources if source.id in selected]
        missing = selected - {source.id for source in sources}
        if missing:
            parser.error(f"来源 ID 不存在：{', '.join(sorted(missing))}")
    if args.limit is not None:
        sources = sources[:args.limit]
    catalog = CatalogStore(config.database_path)
    store = ClickHouseCatalogStore(config.clickhouse)
    metadata = MySQLMetadataStore(config.mysql)
    archive = ObjectArchive.from_config(config.minio)
    try:
        if args.initialize:
            import_result = import_files(catalog, sources)
            if import_result["failed"]:
                raise RuntimeError("部分原始文件导入失败，在线发布已中止")
            local_config = replace(config, storage_mode="local", redis={**config.redis, "enabled": False})
            market = MarketService(local_config)
            try:
                market.initialize()
            finally:
                market.close()
            print(f"本地导入与模型快照完成：{import_result}", flush=True)
        publisher = OnlinePublisher(catalog, store, metadata, archive, rule_settings=config.alerts)
        if args.verify_only:
            differences = [*publisher.migrator.verify_counts(catalog), *publisher.migrator.verify_queries(catalog), *metadata.verify_against(catalog)]
            if differences:
                raise RuntimeError("在线存储核对失败：" + "；".join(differences[:10]))
            for source in sources:
                archived = metadata.object_for_source(source.id)
                if not archived:
                    raise RuntimeError(f"缺少对象元数据：{source.id}")
                archive.verify(source, archived)
            print(f"在线存储与 {len(sources)} 个原始对象核对通过", flush=True)
            return 0
        result = publisher.publish(sources, only_changed=not args.source_id)
        print(f"在线增量发布完成：{result}", flush=True)
        return 0
    finally:
        catalog.close()
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
