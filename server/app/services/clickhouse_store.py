from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Callable, TypeVar

import clickhouse_connect

from app.core.config import SERVER_ROOT
from app.services.mysql_metadata import sql_statements

ANALYTIC_TABLES = (
    "dwd_source_files",
    "dwd_source_records",
    "dwd_source_record_tags",
    "dws_source_daily_stats",
    "dws_source_fields",
    "dws_source_tag_stats",
    "dws_market_features",
    "ads_market_states",
    "ads_alerts",
)

PUBLICATION_TABLES = ("catalog_publication_runs", "catalog_publications")
Result = TypeVar("Result")


def synchronized(method: Callable[..., Result]) -> Callable[..., Result]:
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


def iso_date(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def insert_blocks(rows: list[tuple], columns: list[str], max_partitions: int = 50, max_rows: int = 10000) -> list[list[tuple]]:
    if "event_date" not in columns:
        return [rows[offset:offset + max_rows] for offset in range(0, len(rows), max_rows)]
    date_index = columns.index("event_date")
    groups: dict[tuple[int, int] | None, list[tuple]] = {}
    for row in rows:
        value = row[date_index]
        key = (value.year, value.month) if value is not None else None
        groups.setdefault(key, []).append(row)
    blocks = []
    current: list[tuple] = []
    partition_count = 0
    for group in groups.values():
        for offset in range(0, len(group), max_rows):
            chunk = group[offset:offset + max_rows]
            if partition_count >= max_partitions or len(current) + len(chunk) > max_rows:
                if current:
                    blocks.append(current)
                current = []
                partition_count = 0
            current.extend(chunk)
            partition_count += 1
    if current:
        blocks.append(current)
    return blocks


class Parameters:
    def __init__(self):
        self.values: dict[str, Any] = {}

    def add(self, value: Any, type_name: str = "String") -> str:
        name = f"p{len(self.values)}"
        self.values[name] = value
        return "{" + f"{name}:{type_name}" + "}"


class ClickHouseCatalogStore:
    def __init__(self, settings: dict[str, Any], client: Any = None, migrations_path: Path | None = None):
        self.settings = settings
        self._client = client
        self._lock = RLock()
        self.migrations_path = migrations_path or SERVER_ROOT / "migrations" / "clickhouse"
        if not re.fullmatch(r"[A-Za-z0-9_]+", settings["database"]):
            raise ValueError("ClickHouse 数据库名只能包含字母、数字和下划线")

    def _new_client(self, database: str) -> Any:
        return clickhouse_connect.get_client(
            host=self.settings["host"],
            port=int(self.settings["port"]),
            username=self.settings["username"],
            password=self.settings["password"],
            database=database,
            secure=bool(self.settings.get("secure", False)),
            connect_timeout=5,
            send_receive_timeout=300,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._new_client(self.settings["database"])
        return self._client

    def initialize(self) -> list[str]:
        if self._client is None:
            bootstrap = self._new_client("default")
            try:
                bootstrap.command(f"CREATE DATABASE IF NOT EXISTS `{self.settings['database']}`")
            finally:
                bootstrap.close()
        else:
            self.client.command(f"CREATE DATABASE IF NOT EXISTS `{self.settings['database']}`")
        self.client.command("CREATE TABLE IF NOT EXISTS schema_migrations (version String, applied_at DateTime64(6) DEFAULT now64(6)) ENGINE = MergeTree ORDER BY version")
        applied = []
        for path in sorted(self.migrations_path.glob("*.sql")):
            version = path.stem
            exists = self.client.query("SELECT 1 FROM schema_migrations WHERE version = {version:String}", parameters={"version": version}).result_rows
            if exists:
                continue
            for statement in sql_statements(path.read_text(encoding="utf-8")):
                self.client.command(statement)
            self.client.insert("schema_migrations", [(version,)], column_names=["version"])
            applied.append(version)
        return applied

    def reset(self) -> None:
        for table in (*ANALYTIC_TABLES, *PUBLICATION_TABLES):
            self.client.command(f"TRUNCATE TABLE {table}")

    def published_versions(self) -> dict[str, tuple[int, int, int]]:
        rows = self.client.query("SELECT f.id, f.size, f.mtime_ns, f.generation FROM dwd_source_files f INNER JOIN catalog_publications AS p FINAL ON f.id = p.source_id AND f.generation = p.generation").result_rows
        return {row[0]: (int(row[1]), int(row[2]), int(row[3])) for row in rows}

    def discard_staged(self, source_id: str, generation: int) -> None:
        parameters = {"source_id": source_id, "generation": generation}
        for table in ANALYTIC_TABLES[:6]:
            key = "id" if table == "dwd_source_files" else "source_id"
            condition = f"{key} = {{source_id:String}} AND generation = {{generation:UInt64}}"
            exists = self.client.query(f"SELECT 1 FROM {table} WHERE {condition} LIMIT 1", parameters=parameters).result_rows
            if exists:
                self.client.command(f"ALTER TABLE {table} DELETE WHERE {condition} SETTINGS mutations_sync = 2", parameters=parameters)

    def record_run(self, source_id: str, generation: int, status: str, record_count: int = 0, error: str | None = None) -> None:
        self.insert(
            "catalog_publication_runs",
            [(source_id, generation, status, record_count, error)],
            ["source_id", "generation", "status", "record_count", "error"],
        )

    def activate(self, source_id: str, generation: int, record_count: int) -> None:
        self.insert("catalog_publications", [(source_id, generation, record_count)], ["source_id", "generation", "record_count"])
        self.record_run(source_id, generation, "published", record_count)

    def insert(self, table: str, rows: list[tuple], columns: list[str]) -> None:
        date_columns = {index for index, name in enumerate(columns) if name in {"event_date", "trained_through"}}
        if date_columns:
            rows = [tuple(date.fromisoformat(value) if index in date_columns and isinstance(value, str) else value for index, value in enumerate(row)) for row in rows]
        for block in insert_blocks(rows, columns):
            self.client.insert(table, block, column_names=columns)

    @synchronized
    def data_version(self) -> str:
        rows = self.client.query("SELECT source_id, generation, record_count FROM catalog_publications AS p FINAL ORDER BY source_id").result_rows
        return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()

    @synchronized
    def summary(self) -> dict[str, Any]:
        row = self.client.query("SELECT COUNT(*), sum(status = 'imported'), sum(record_count), sum(error_count) FROM active_source_files").result_rows[0]
        groups = self.client.query("SELECT kind, COUNT(*), sum(record_count) FROM active_source_files GROUP BY kind ORDER BY kind").result_rows
        return {"total_files": int(row[0]), "imported_files": int(row[1]), "total_records": int(row[2]), "errors": int(row[3]), "groups": [{"kind": item[0], "files": int(item[1]), "records": int(item[2])} for item in groups]}

    @synchronized
    def overview(self, kind: str | None) -> dict[str, Any]:
        params = Parameters()
        where = f"WHERE kind = {params.add(kind)}" if kind else ""
        join_where = f"WHERE f.kind = {params.add(kind)}" if kind else ""
        totals = self.client.query(f"SELECT COUNT(*), sum(record_count) FROM active_source_files {where}", parameters=params.values).result_rows[0]
        dates = self.client.query(f"SELECT min(d.event_date), max(d.event_date), sum(d.record_count) FROM active_source_daily_stats d INNER JOIN active_source_files f ON f.id = d.source_id {join_where}", parameters=params.values).result_rows[0]
        start, end, dated_records = dates
        granularity = "day"
        if start and end:
            span = (end - start).days
            granularity = "month" if span > 120 else "day"
            if span > 3650:
                granularity = "year"
        expression = {"day": "toString(d.event_date)", "month": "formatDateTime(d.event_date, '%Y-%m')", "year": "formatDateTime(d.event_date, '%Y')"}[granularity]
        trend = self.client.query(f"SELECT {expression}, sum(d.record_count) FROM active_source_daily_stats d INNER JOIN active_source_files f ON f.id = d.source_id {join_where} GROUP BY {expression} ORDER BY {expression}", parameters=params.values).result_rows
        fields = self.client.query(f"SELECT d.name, min(d.field_position), sum(d.non_null_count) FROM active_source_fields d INNER JOIN active_source_files f ON f.id = d.source_id {join_where} GROUP BY d.name ORDER BY min(d.field_position), d.name LIMIT 100", parameters=params.values).result_rows
        return {
            "kind": kind,
            "files": int(totals[0]),
            "records": int(totals[1]),
            "start_date": iso_date(start),
            "end_date": iso_date(end),
            "undated_records": int(totals[1] - (dated_records or 0)),
            "granularity": granularity,
            "trend": [{"period": period, "count": int(count)} for period, count in trend],
            "fields": [{"name": name, "non_null_count": int(count)} for name, _, count in fields],
        }

    @synchronized
    def list_tags(self, kind: str | None) -> list[dict[str, Any]]:
        params = Parameters()
        where = f"WHERE kind = {params.add(kind)}" if kind else ""
        rows = self.client.query(f"SELECT tag, sum(record_count) FROM active_source_tag_stats {where} GROUP BY tag ORDER BY sum(record_count) DESC, tag LIMIT 100", parameters=params.values).result_rows
        return [{"tag": tag, "records": int(count)} for tag, count in rows]

    @synchronized
    def list_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        params = Parameters()
        conditions = []
        if kind:
            conditions.append(f"kind = {params.add(kind)}")
        if query:
            conditions.append(f"path ILIKE {params.add(f'%{query}%')}")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total = self.client.query(f"SELECT COUNT(*) FROM active_source_files {where}", parameters=params.values).result_rows[0][0]
        rows = self.client.query(
            f"SELECT id, kind, path, status, record_count, error_count, sheets_json, error, size, mtime_ns FROM active_source_files {where} ORDER BY kind, path LIMIT {int(limit)} OFFSET {int(offset)}",
            parameters=params.values,
        ).result_rows
        return {"total": int(total), "offset": offset, "limit": limit, "items": [{"id": row[0], "kind": row[1], "path": row[2], "status": row[3], "record_count": int(row[4]), "error_count": int(row[5]), "sheets": json.loads(row[6]), "error": row[7], "size": int(row[8]), "mtime_ns": int(row[9])} for row in rows]}

    @synchronized
    def list_records(self, source_id: str | None, query: str | None, date: str | None, offset: int, limit: int, kind: str | None = None, tag: str | None = None, tags: list[str] | None = None, match: str = "any") -> dict[str, Any]:
        selected_tags = list(dict.fromkeys(tags or ([tag] if tag else [])))
        if len(selected_tags) > 5:
            raise ValueError("最多同时筛选 5 个标签")
        if match not in {"any", "all"}:
            raise ValueError("标签匹配方式必须为 any 或 all")
        params = Parameters()
        conditions = []
        if source_id:
            conditions.append(f"r.source_id = {params.add(source_id)}")
        if kind:
            conditions.append(f"r.kind = {params.add(kind)}")
        if query:
            conditions.append(f"r.title ILIKE {params.add(f'%{query}%')}")
        if date:
            conditions.append(f"r.event_date = {params.add(date, 'Date32')}")
        group_clause = ""
        order = "r.event_date DESC, r.source_id, r.record_index DESC"
        if selected_tags:
            placeholders = ",".join(params.add(item) for item in selected_tags)
            conditions.append(f"tag_filter.tag IN ({placeholders})")
            conditions.append("tag_filter.kind = r.kind")
            from_clause = "FROM active_source_record_tags tag_filter INNER JOIN active_source_records r ON r.source_id = tag_filter.source_id AND r.record_index = tag_filter.record_index INNER JOIN active_source_files f ON f.id = r.source_id"
            if len(selected_tags) > 1:
                group_clause = "GROUP BY r.source_id, r.record_index"
                if match == "all":
                    group_clause += f" HAVING uniqExact(tag_filter.tag) = {len(selected_tags)}"
                order = "max(tag_filter.event_date) DESC, tag_filter.source_id, tag_filter.record_index DESC"
            else:
                order = "tag_filter.event_date DESC, tag_filter.source_id, tag_filter.record_index DESC"
        else:
            from_clause = "FROM active_source_records r INNER JOIN active_source_files f ON f.id = r.source_id"
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        if not query and not date and len(selected_tags) <= 1:
            count_params = Parameters()
            count_conditions = []
            if source_id:
                count_conditions.append(f"source_id = {count_params.add(source_id)}" if selected_tags else f"id = {count_params.add(source_id)}")
            if kind:
                count_conditions.append(f"kind = {count_params.add(kind)}")
            if len(selected_tags) == 1:
                count_conditions.append(f"tag = {count_params.add(selected_tags[0])}")
            count_where = f"WHERE {' AND '.join(count_conditions)}" if count_conditions else ""
            count_table = "active_source_tag_stats" if selected_tags else "active_source_files"
            total = self.client.query(f"SELECT sum(record_count) FROM {count_table} {count_where}", parameters=count_params.values).result_rows[0][0]
        elif len(selected_tags) > 1:
            if not query and not date:
                count_params = Parameters()
                placeholders = ",".join(count_params.add(item) for item in selected_tags)
                tag_conditions = [f"tag IN ({placeholders})"]
                if source_id:
                    tag_conditions.append(f"source_id = {count_params.add(source_id)}")
                if kind:
                    tag_conditions.append(f"kind = {count_params.add(kind)}")
                having = f" HAVING uniqExact(tag) = {len(selected_tags)}" if match == "all" else ""
                total = self.client.query(f"SELECT COUNT(*) FROM (SELECT source_id, record_index FROM active_source_record_tags WHERE {' AND '.join(tag_conditions)} GROUP BY source_id, record_index{having})", parameters=count_params.values).result_rows[0][0]
            else:
                total = self.client.query(f"SELECT COUNT(*) FROM (SELECT r.source_id, r.record_index {from_clause} {where} {group_clause})", parameters=params.values).result_rows[0][0]
        else:
            total = self.client.query(f"SELECT COUNT(*) {from_clause} {where}", parameters=params.values).result_rows[0][0]
        if selected_tags:
            if len(selected_tags) > 1 and not query and not date:
                row_params = Parameters()
                placeholders = ",".join(row_params.add(item) for item in selected_tags)
                row_conditions = [f"tag IN ({placeholders})"]
                if source_id:
                    row_conditions.append(f"source_id = {row_params.add(source_id)}")
                if kind:
                    row_conditions.append(f"kind = {row_params.add(kind)}")
                having = f" HAVING uniqExact(tag) = {len(selected_tags)}" if match == "all" else ""
                selected_rows = f"SELECT source_id, record_index, max(event_date) AS event_date FROM active_source_record_tags WHERE {' AND '.join(row_conditions)} GROUP BY source_id, record_index{having} ORDER BY event_date DESC, source_id, record_index DESC LIMIT {int(limit)} OFFSET {int(offset)}"
            else:
                selected_date = "max(tag_filter.event_date)" if len(selected_tags) > 1 else "tag_filter.event_date"
                selected_rows = f"SELECT r.source_id AS source_id, r.record_index AS record_index, {selected_date} AS event_date {from_clause} {where} {group_clause} ORDER BY {order} LIMIT {int(limit)} OFFSET {int(offset)}"
                row_params = params
            selected_rows = selected_rows.replace("active_source_records r ", "active_source_records inner_r ").replace("active_source_files f ", "active_source_files inner_f ")
            selected_rows = re.sub(r"\br\.", "inner_r.", selected_rows)
            selected_rows = re.sub(r"\bf\.", "inner_f.", selected_rows)
            rows = self.client.query(
                f"SELECT r.source_id, f.path, f.kind, r.record_index, r.event_date, r.title, r.payload_json, (SELECT groupUniqArray(t.tag) FROM active_source_record_tags t WHERE t.source_id = r.source_id AND t.record_index = r.record_index) FROM ({selected_rows}) selected INNER JOIN active_source_records r ON r.source_id = selected.source_id AND r.record_index = selected.record_index INNER JOIN active_source_files f ON f.id = r.source_id ORDER BY selected.event_date DESC, selected.source_id, selected.record_index DESC",
                parameters=row_params.values,
            ).result_rows
        else:
            rows = self.client.query(
                f"SELECT r.source_id, f.path, f.kind, r.record_index, r.event_date, r.title, r.payload_json, (SELECT groupUniqArray(t.tag) FROM active_source_record_tags t WHERE t.source_id = r.source_id AND t.record_index = r.record_index) {from_clause} {where} {group_clause} ORDER BY {order} LIMIT {int(limit)} OFFSET {int(offset)}",
                parameters=params.values,
            ).result_rows
        return {"total": int(total or 0), "offset": offset, "limit": limit, "items": [{"source_id": row[0], "source_path": row[1], "kind": row[2], "record_index": int(row[3]), "event_date": iso_date(row[4]), "title": row[5], "payload": json.loads(row[6]), "tags": sorted(row[7])} for row in rows]}

    @synchronized
    def close(self) -> None:
        if self._client is not None:
            self._client.close()
