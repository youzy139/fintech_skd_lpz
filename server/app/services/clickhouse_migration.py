from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.services.catalog import CatalogStore
from app.services.clickhouse_store import ClickHouseCatalogStore
from app.services.migration_baseline import BASELINE_VERSION, catalog_queries, compare_baselines

FILE_COLUMNS = ["id", "kind", "path", "size", "mtime_ns", "status", "record_count", "error_count", "sheets_json", "error", "updated_at", "transformation_version", "generation"]
RECORD_COLUMNS = ["source_id", "record_index", "kind", "source_path", "import_batch_id", "event_date", "title", "payload_json", "transformation_version", "generation"]
TAG_COLUMNS = ["source_id", "record_index", "kind", "tag", "event_date", "transformation_version", "generation"]


class ClickHouseMigrator:
    def __init__(self, store: ClickHouseCatalogStore, rule_settings: dict[str, Any], transformation_version: str = "sqlite-stage-c-v1"):
        self.store = store
        self.transformation_version = transformation_version
        self.rule_version = "rules-" + hashlib.sha256(json.dumps(rule_settings, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def migrate(self, catalog: CatalogStore, reset: bool = True, generation: int = 1) -> dict[str, int]:
        self.store.initialize()
        if reset:
            self.store.reset()
        counts = {"files": 0, "records": 0, "tags": 0, "features": 0, "states": 0, "alerts": 0}
        latest_batches = {row[0]: row[1] for row in catalog.connection.execute("SELECT source_id, MAX(id) FROM import_batches GROUP BY source_id")}
        files = catalog.connection.execute("SELECT id, kind, path, size, mtime_ns, status, record_count, error_count, sheets_json, error, updated_at FROM source_files ORDER BY id").fetchall()
        file_rows = [(*row[:10], datetime.fromisoformat(row[10]), self.transformation_version, generation) for row in files]
        self.store.insert("dwd_source_files", file_rows, FILE_COLUMNS)
        counts["files"] = len(file_rows)
        for source_id, kind, path, *_ in files:
            batch_id = latest_batches.get(source_id, 0)
            cursor = catalog.connection.execute("SELECT record_index, event_date, title, payload_json FROM source_records WHERE source_id = ? ORDER BY record_index", (source_id,))
            while rows := cursor.fetchmany(1000):
                self.store.insert("dwd_source_records", [(source_id, index, kind, path, batch_id, day, title, payload, self.transformation_version, generation) for index, day, title, payload in rows], RECORD_COLUMNS)
                counts["records"] += len(rows)
            cursor = catalog.connection.execute("SELECT record_index, tag, event_date FROM source_record_tags WHERE source_id = ? ORDER BY record_index, tag", (source_id,))
            while rows := cursor.fetchmany(5000):
                self.store.insert("dwd_source_record_tags", [(source_id, index, kind, tag, day, self.transformation_version, generation) for index, tag, day in rows], TAG_COLUMNS)
                counts["tags"] += len(rows)
        self._migrate_statistics(catalog, generation)
        for row in files:
            self.store.activate(row[0], generation, int(row[6]))
        counts.update(self._migrate_market(catalog))
        return counts

    def _migrate_statistics(self, catalog: CatalogStore, generation: int) -> None:
        daily = catalog.connection.execute("SELECT source_id, event_date, record_count FROM source_daily_stats ORDER BY source_id, event_date").fetchall()
        self.store.insert("dws_source_daily_stats", [(*row, self.transformation_version, generation) for row in daily], ["source_id", "event_date", "record_count", "transformation_version", "generation"])
        fields = catalog.connection.execute("SELECT source_id, name, field_position, non_null_count FROM source_fields ORDER BY source_id, name").fetchall()
        self.store.insert("dws_source_fields", [(*row, self.transformation_version, generation) for row in fields], ["source_id", "name", "field_position", "non_null_count", "transformation_version", "generation"])
        tags = catalog.connection.execute("SELECT source_id, kind, tag, record_count FROM source_tag_stats ORDER BY source_id, tag").fetchall()
        self.store.insert("dws_source_tag_stats", [(*row, self.transformation_version, generation) for row in tags], ["source_id", "kind", "tag", "record_count", "transformation_version", "generation"])

    def refresh_market(self, catalog: CatalogStore) -> dict[str, int]:
        for table in ("dws_market_features", "ads_market_states", "ads_alerts"):
            self.store.client.command(f"TRUNCATE TABLE {table}")
        return self._migrate_market(catalog)

    def _migrate_market(self, catalog: CatalogStore) -> dict[str, int]:
        snapshots = dict(catalog.connection.execute("SELECT key, value_json FROM snapshots").fetchall())
        states = json.loads(snapshots.get("states", "[]"))
        alerts = json.loads(snapshots.get("alerts", "[]"))
        feature_rows = []
        state_rows = []
        for state in states:
            for feature, value in state["features"].items():
                feature_rows.append((state["date"], feature, value, state["model_version"], self.transformation_version))
            state_rows.append((state["date"], state["cluster"], state["label"], state["confidence"], state["model_version"], state["trained_through"], json.dumps(state["features"], ensure_ascii=False), json.dumps(state["contributions"], ensure_ascii=False), self.transformation_version))
        self.store.insert("dws_market_features", feature_rows, ["event_date", "feature", "value", "model_version", "transformation_version"])
        self.store.insert("ads_market_states", state_rows, ["event_date", "cluster", "label", "confidence", "model_version", "trained_through", "features_json", "contributions_json", "transformation_version"])
        alert_rows = [(item["date"], item["rule"], self.rule_version, item["level"], item["title"], item["evidence"], item.get("value"), item.get("threshold"), self.transformation_version) for item in alerts]
        self.store.insert("ads_alerts", alert_rows, ["event_date", "rule", "rule_version", "level", "title", "evidence", "value", "threshold", "transformation_version"])
        return {"features": len(feature_rows), "states": len(state_rows), "alerts": len(alert_rows)}

    def verify_counts(self, catalog: CatalogStore) -> list[str]:
        differences = []
        checks = (
            ("source_records", "active_source_records"),
            ("source_record_tags", "active_source_record_tags"),
            ("source_daily_stats", "active_source_daily_stats"),
            ("source_fields", "active_source_fields"),
            ("source_tag_stats", "active_source_tag_stats"),
        )
        for sqlite_table, clickhouse_table in checks:
            expected = catalog.connection.execute(f"SELECT COUNT(*) FROM {sqlite_table}").fetchone()[0]
            actual = self.store.client.query(f"SELECT COUNT(*) FROM {clickhouse_table}").result_rows[0][0]
            if expected != actual:
                differences.append(f"{clickhouse_table}: {expected} != {actual}")
        expected_states = json.loads(catalog.connection.execute("SELECT value_json FROM snapshots WHERE key = 'states'").fetchone()[0])
        expected_alerts = json.loads(catalog.connection.execute("SELECT value_json FROM snapshots WHERE key = 'alerts'").fetchone()[0])
        for table, expected in (("ads_market_states", len(expected_states)), ("ads_alerts", len(expected_alerts)), ("dws_market_features", len(expected_states) * 6)):
            actual = self.store.client.query(f"SELECT COUNT(*) FROM {table}").result_rows[0][0]
            if expected != actual:
                differences.append(f"{table}: {expected} != {actual}")
        return differences

    def verify_queries(self, catalog: CatalogStore, query_limit: int = 20) -> list[str]:
        expected = catalog_queries(catalog, query_limit)
        actual = catalog_queries(self.store, query_limit)
        wrapped = {"baseline_version": BASELINE_VERSION, "query_limit": query_limit, "includes_record_digests": False}
        return compare_baselines({**wrapped, "payload": expected}, {**wrapped, "payload": actual})
