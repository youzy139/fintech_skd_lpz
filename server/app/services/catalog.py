from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date as calendar_date
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable, TypeVar

from market_core.domain.sources import SourceFile, SourceRecord
from market_core.domain.tags import record_tags
from market_core.ingestion.sources import iter_records, source_sheets


Result = TypeVar("Result")


def synchronized(method: Callable[..., Result]) -> Callable[..., Result]:
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class CatalogStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        record_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(source_records)")}
        if record_columns and "kind" not in record_columns:
            self.connection.execute("ALTER TABLE source_records ADD COLUMN kind TEXT")
        tag_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(source_record_tags)")}
        if tag_columns and "event_date" not in tag_columns:
            self.connection.execute("ALTER TABLE source_record_tags ADD COLUMN event_date TEXT")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS source_files (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT UNIQUE NOT NULL,
                size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, status TEXT NOT NULL,
                record_count INTEGER NOT NULL DEFAULT 0, error_count INTEGER NOT NULL DEFAULT 0,
                sheets_json TEXT NOT NULL DEFAULT '[]', error TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS source_records (
                source_id TEXT NOT NULL, record_index INTEGER NOT NULL,
                event_date TEXT, title TEXT NOT NULL, payload_json TEXT NOT NULL, kind TEXT,
                PRIMARY KEY (source_id, record_index)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_records_date ON source_records(event_date);
            CREATE INDEX IF NOT EXISTS idx_records_date_source ON source_records(event_date DESC, source_id, record_index DESC);
            CREATE INDEX IF NOT EXISTS idx_records_kind_date ON source_records(kind, event_date DESC, source_id, record_index DESC);
            CREATE INDEX IF NOT EXISTS idx_records_title ON source_records(title);
            CREATE INDEX IF NOT EXISTS idx_records_source_date ON source_records(source_id, event_date DESC, record_index DESC);
            CREATE INDEX IF NOT EXISTS idx_records_source_title ON source_records(source_id, title);
            CREATE INDEX IF NOT EXISTS idx_files_kind ON source_files(kind);
            CREATE TABLE IF NOT EXISTS source_daily_stats (
                source_id TEXT NOT NULL, event_date TEXT NOT NULL, record_count INTEGER NOT NULL,
                PRIMARY KEY (source_id, event_date)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS source_fields (
                source_id TEXT NOT NULL, name TEXT NOT NULL, field_position INTEGER NOT NULL,
                non_null_count INTEGER NOT NULL, PRIMARY KEY (source_id, name)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS source_record_tags (
                source_id TEXT NOT NULL, record_index INTEGER NOT NULL, kind TEXT NOT NULL,
                tag TEXT NOT NULL, event_date TEXT, PRIMARY KEY (source_id, record_index, tag)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_record_tags_filter ON source_record_tags(tag, kind, event_date DESC, source_id, record_index DESC);
            CREATE INDEX IF NOT EXISTS idx_record_tags_tag_kind ON source_record_tags(tag, kind, source_id, record_index);
            CREATE INDEX IF NOT EXISTS idx_record_tags_kind_tag ON source_record_tags(kind, tag, source_id, record_index);
            CREATE TABLE IF NOT EXISTS source_tag_stats (
                source_id TEXT NOT NULL, kind TEXT NOT NULL, tag TEXT NOT NULL,
                record_count INTEGER NOT NULL, PRIMARY KEY (source_id, tag)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_tag_stats_kind ON source_tag_stats(kind, tag);
            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
                status TEXT NOT NULL, record_count INTEGER NOT NULL DEFAULT 0,
                error TEXT, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            );
            """
        )
        self.connection.execute("UPDATE source_records SET kind=(SELECT kind FROM source_files WHERE id=source_id) WHERE kind IS NULL")
        self.connection.execute("UPDATE source_record_tags SET event_date=(SELECT event_date FROM source_records WHERE source_id=source_record_tags.source_id AND record_index=source_record_tags.record_index) WHERE event_date IS NULL")
        self.connection.commit()

    @synchronized
    def is_unchanged(self, source: SourceFile) -> bool:
        row = self.connection.execute("SELECT 1 FROM source_files WHERE id = ? AND size = ? AND mtime_ns = ? AND status = 'imported'", (source.id, source.size, source.mtime_ns)).fetchone()
        return row is not None

    @synchronized
    def import_file(self, source: SourceFile, batch_size: int = 1000) -> dict[str, Any]:
        cursor = self.connection.execute("INSERT INTO import_batches (source_id, status) VALUES (?, 'running')", (source.id,))
        batch_id = cursor.lastrowid
        self.connection.execute(
            "INSERT INTO source_files (id, kind, path, size, mtime_ns, status) VALUES (?, ?, ?, ?, ?, 'importing') ON CONFLICT(id) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, status='importing', error=NULL",
            (source.id, source.kind, source.path, source.size, source.mtime_ns),
        )
        for table in ("source_records", "source_daily_stats", "source_fields", "source_record_tags", "source_tag_stats"):
            self.connection.execute(f"DELETE FROM {table} WHERE source_id = ?", (source.id,))
        self.connection.commit()
        count = 0
        daily: Counter[str] = Counter()
        fields: Counter[str] = Counter()
        tag_counts: Counter[str] = Counter()
        positions: dict[str, int] = {}
        try:
            batch: list[tuple] = []
            tag_batch: list[tuple] = []
            for record in iter_records(source):
                batch.append(self._record_tuple(record, source.kind))
                self._accumulate_statistics(record, daily, fields, positions)
                tags = record_tags(record.title, record.payload)
                tag_counts.update(tags)
                tag_batch.extend((source.id, record.record_index, source.kind, tag, record.event_date) for tag in tags)
                if len(batch) >= batch_size:
                    self._write_batch(batch, tag_batch)
                    count += len(batch)
                    batch, tag_batch = [], []
            if batch:
                self._write_batch(batch, tag_batch)
                count += len(batch)
            sheets = source_sheets(source)
            self._write_statistics(source.id, source.kind, daily, fields, positions, tag_counts)
            self.connection.execute("UPDATE source_files SET status='imported', record_count=?, error_count=0, sheets_json=?, error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", (count, json.dumps(sheets), source.id))
            self.connection.execute("UPDATE import_batches SET status='completed', record_count=?, completed_at=CURRENT_TIMESTAMP WHERE id=?", (count, batch_id))
            self.connection.commit()
            return {"id": source.id, "status": "imported", "record_count": count}
        except Exception as error:
            self.connection.execute("UPDATE source_files SET status='failed', record_count=?, error_count=1, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (count, str(error), source.id))
            self.connection.execute("UPDATE import_batches SET status='failed', record_count=?, error=?, completed_at=CURRENT_TIMESTAMP WHERE id=?", (count, str(error), batch_id))
            self.connection.commit()
            raise

    @staticmethod
    def _record_tuple(record: SourceRecord, kind: str) -> tuple:
        return (record.source_id, record.record_index, record.event_date, record.title, json.dumps(record.payload, ensure_ascii=False, default=str), kind)

    @synchronized
    def _write_batch(self, batch: Iterable[tuple], tag_batch: Iterable[tuple]) -> None:
        self.connection.executemany("INSERT INTO source_records (source_id, record_index, event_date, title, payload_json, kind) VALUES (?, ?, ?, ?, ?, ?)", batch)
        self.connection.executemany("INSERT INTO source_record_tags (source_id, record_index, kind, tag, event_date) VALUES (?, ?, ?, ?, ?)", tag_batch)
        self.connection.commit()

    @staticmethod
    def _accumulate_statistics(record: SourceRecord, daily: Counter[str], fields: Counter[str], positions: dict[str, int]) -> None:
        if record.event_date:
            daily[record.event_date] += 1
        for name, value in record.payload.items():
            positions.setdefault(name, len(positions))
            if value is not None and value != "":
                fields[name] += 1

    @synchronized
    def _write_statistics(self, source_id: str, kind: str, daily: Counter[str], fields: Counter[str], positions: dict[str, int], tag_counts: Counter[str]) -> None:
        self.connection.executemany(
            "INSERT INTO source_daily_stats (source_id, event_date, record_count) VALUES (?, ?, ?)",
            [(source_id, day, count) for day, count in daily.items()],
        )
        self.connection.executemany(
            "INSERT INTO source_fields (source_id, name, field_position, non_null_count) VALUES (?, ?, ?, ?)",
            [(source_id, name, positions[name], count) for name, count in fields.items()],
        )
        self.connection.executemany(
            "INSERT INTO source_tag_stats (source_id, kind, tag, record_count) VALUES (?, ?, ?, ?)",
            [(source_id, kind, tag, count) for tag, count in tag_counts.items()],
        )

    @synchronized
    def rebuild_statistics(self) -> dict[str, int]:
        for table in ("source_daily_stats", "source_fields", "source_record_tags", "source_tag_stats"):
            self.connection.execute(f"DELETE FROM {table}")
        self.connection.commit()
        cursor = self.connection.execute("SELECT source_id, record_index, event_date, title, payload_json, kind FROM source_records ORDER BY source_id, record_index")
        current_id: str | None = None
        current_kind = ""
        daily: Counter[str] = Counter()
        fields: Counter[str] = Counter()
        tag_counts: Counter[str] = Counter()
        positions: dict[str, int] = {}
        tag_batch: list[tuple] = []
        sources = 0
        rows = 0
        while True:
            batch = cursor.fetchmany(1000)
            if not batch:
                break
            for source_id, record_index, event_date, title, payload_json, kind in batch:
                if current_id is not None and source_id != current_id:
                    self._write_statistics(current_id, current_kind, daily, fields, positions, tag_counts)
                    self.connection.commit()
                    sources += 1
                    daily, fields, tag_counts, positions = Counter(), Counter(), Counter(), {}
                current_id, current_kind = source_id, kind
                record = SourceRecord(source_id, record_index, event_date, title, json.loads(payload_json))
                self._accumulate_statistics(record, daily, fields, positions)
                tags = record_tags(title, record.payload)
                tag_counts.update(tags)
                tag_batch.extend((source_id, record_index, kind, tag, event_date) for tag in tags)
                rows += 1
            if tag_batch:
                self.connection.executemany("INSERT INTO source_record_tags (source_id, record_index, kind, tag, event_date) VALUES (?, ?, ?, ?, ?)", tag_batch)
                tag_batch = []
            self.connection.commit()
        if current_id is not None:
            self._write_statistics(current_id, current_kind, daily, fields, positions, tag_counts)
            sources += 1
        self.connection.commit()
        return {"sources": sources, "records": rows}

    @synchronized
    def data_version(self) -> str:
        rows = self.connection.execute("SELECT id, size, mtime_ns, status, record_count, error_count, updated_at FROM source_files ORDER BY id").fetchall()
        return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()

    @synchronized
    def summary(self) -> dict[str, Any]:
        row = self.connection.execute("SELECT COUNT(*), COALESCE(SUM(status='imported'),0), COALESCE(SUM(record_count),0), COALESCE(SUM(error_count),0) FROM source_files").fetchone()
        groups = self.connection.execute("SELECT kind, COUNT(*), COALESCE(SUM(record_count),0) FROM source_files GROUP BY kind ORDER BY kind").fetchall()
        return {"total_files": row[0], "imported_files": row[1], "total_records": row[2], "errors": row[3], "groups": [{"kind": item[0], "files": item[1], "records": item[2]} for item in groups]}

    @synchronized
    def overview(self, kind: str | None) -> dict[str, Any]:
        where = "WHERE kind = ?" if kind else ""
        join_where = "WHERE f.kind = ?" if kind else ""
        params = (kind,) if kind else ()
        totals = self.connection.execute(f"SELECT COUNT(*), COALESCE(SUM(record_count),0) FROM source_files {where}", params).fetchone()
        dates = self.connection.execute(f"SELECT MIN(d.event_date), MAX(d.event_date), COALESCE(SUM(d.record_count),0) FROM source_daily_stats d JOIN source_files f ON f.id=d.source_id {join_where}", params).fetchone()
        start, end, dated_records = dates
        granularity = "day"
        if start and end:
            try:
                span = (calendar_date.fromisoformat(end) - calendar_date.fromisoformat(start)).days
                granularity = "month" if span > 120 else "day"
                if span > 3650:
                    granularity = "year"
            except ValueError:
                granularity = "month"
        expression = {"day": "d.event_date", "month": "substr(d.event_date,1,7)", "year": "substr(d.event_date,1,4)"}[granularity]
        trend = self.connection.execute(f"SELECT {expression}, SUM(d.record_count) FROM source_daily_stats d JOIN source_files f ON f.id=d.source_id {join_where} GROUP BY {expression} ORDER BY {expression}", params).fetchall()
        fields = self.connection.execute(f"SELECT d.name, MIN(d.field_position), SUM(d.non_null_count) FROM source_fields d JOIN source_files f ON f.id=d.source_id {join_where} GROUP BY d.name ORDER BY MIN(d.field_position), d.name LIMIT 100", params).fetchall()
        return {
            "kind": kind, "files": totals[0], "records": totals[1], "start_date": start, "end_date": end,
            "undated_records": totals[1] - dated_records, "granularity": granularity,
            "trend": [{"period": period, "count": count} for period, count in trend],
            "fields": [{"name": name, "non_null_count": count} for name, _, count in fields],
        }

    @synchronized
    def list_tags(self, kind: str | None) -> list[dict[str, Any]]:
        where = "WHERE kind = ?" if kind else ""
        params = (kind,) if kind else ()
        rows = self.connection.execute(f"SELECT tag, SUM(record_count) FROM source_tag_stats {where} GROUP BY tag ORDER BY SUM(record_count) DESC, tag LIMIT 100", params).fetchall()
        return [{"tag": tag, "records": count} for tag, count in rows]

    @synchronized
    def list_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        conditions: list[str] = []
        params: list[Any] = []
        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        if query:
            conditions.append("path LIKE ?")
            params.append(f"%{query}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total = self.connection.execute(f"SELECT COUNT(*) FROM source_files {where}", params).fetchone()[0]
        rows = self.connection.execute(f"SELECT id, kind, path, status, record_count, error_count, sheets_json, error, size, mtime_ns FROM source_files {where} ORDER BY kind, path LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return {"total": total, "offset": offset, "limit": limit, "items": [self._file_dict(row) for row in rows]}

    @staticmethod
    def _file_dict(row: tuple) -> dict[str, Any]:
        return {"id": row[0], "kind": row[1], "path": row[2], "status": row[3], "record_count": row[4], "error_count": row[5], "sheets": json.loads(row[6]), "error": row[7], "size": row[8], "mtime_ns": row[9]}

    @synchronized
    def list_records(self, source_id: str | None, query: str | None, date: str | None, offset: int, limit: int, kind: str | None = None, tag: str | None = None, tags: list[str] | None = None, match: str = "any") -> dict[str, Any]:
        selected_tags = list(dict.fromkeys(tags or ([tag] if tag else [])))
        if len(selected_tags) > 5:
            raise ValueError("最多同时筛选 5 个标签")
        if match not in {"any", "all"}:
            raise ValueError("标签匹配方式必须为 any 或 all")
        conditions: list[str] = []
        params: list[Any] = []
        if source_id:
            conditions.append("r.source_id = ?")
            params.append(source_id)
        if kind:
            conditions.append("r.kind = ?")
            params.append(kind)
        if query:
            conditions.append("r.title LIKE ?")
            params.append(f"%{query}%")
        if date:
            conditions.append("r.event_date = ?")
            params.append(date)
        group_clause = ""
        order = "r.event_date DESC, r.source_id, r.record_index DESC"
        if selected_tags:
            placeholders = ",".join("?" for _ in selected_tags)
            conditions.append(f"tag_filter.tag IN ({placeholders})")
            conditions.append("tag_filter.kind = r.kind")
            params.extend(selected_tags)
            from_clause = "FROM source_record_tags tag_filter CROSS JOIN source_records r ON r.source_id=tag_filter.source_id AND r.record_index=tag_filter.record_index CROSS JOIN source_files f ON f.id=r.source_id"
            if len(selected_tags) > 1:
                group_clause = "GROUP BY r.source_id, r.record_index"
                if match == "all":
                    group_clause += f" HAVING COUNT(DISTINCT tag_filter.tag) = {len(selected_tags)}"
                order = "MAX(tag_filter.event_date) DESC, tag_filter.source_id, tag_filter.record_index DESC"
            else:
                order = "tag_filter.event_date DESC, tag_filter.source_id, tag_filter.record_index DESC"
        else:
            from_clause = "FROM source_records r JOIN source_files f ON f.id=r.source_id"
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        if not query and not date and len(selected_tags) <= 1:
            count_conditions: list[str] = []
            count_params: list[Any] = []
            if source_id:
                count_conditions.append("source_id = ?" if selected_tags else "id = ?")
                count_params.append(source_id)
            if kind:
                count_conditions.append("kind = ?")
                count_params.append(kind)
            if len(selected_tags) == 1:
                count_conditions.append("tag = ?")
                count_params.append(selected_tags[0])
            count_where = f"WHERE {' AND '.join(count_conditions)}" if count_conditions else ""
            count_table = "source_tag_stats" if selected_tags else "source_files"
            total = self.connection.execute(f"SELECT COALESCE(SUM(record_count),0) FROM {count_table} {count_where}", count_params).fetchone()[0]
        elif len(selected_tags) > 1:
            if not query and not date:
                tag_conditions = ["tag IN (" + ",".join("?" for _ in selected_tags) + ")"]
                count_params: list[Any] = list(selected_tags)
                if source_id:
                    tag_conditions.append("source_id = ?")
                    count_params.append(source_id)
                if kind:
                    tag_conditions.append("kind = ?")
                    count_params.append(kind)
                having = f" HAVING COUNT(DISTINCT tag) = {len(selected_tags)}" if match == "all" else ""
                total = self.connection.execute(f"SELECT COUNT(*) FROM (SELECT source_id, record_index FROM source_record_tags WHERE {' AND '.join(tag_conditions)} GROUP BY source_id, record_index{having})", count_params).fetchone()[0]
            else:
                total = self.connection.execute(f"SELECT COUNT(*) FROM (SELECT r.source_id, r.record_index {from_clause} {where} {group_clause})", params).fetchone()[0]
        else:
            total = self.connection.execute(f"SELECT COUNT(*) {from_clause} {where}", params).fetchone()[0]
        if selected_tags:
            if len(selected_tags) > 1 and not query and not date:
                row_conditions = ["tag IN (" + ",".join("?" for _ in selected_tags) + ")"]
                row_params: list[Any] = list(selected_tags)
                if source_id:
                    row_conditions.append("source_id = ?")
                    row_params.append(source_id)
                if kind:
                    row_conditions.append("kind = ?")
                    row_params.append(kind)
                having = f" HAVING COUNT(DISTINCT tag) = {len(selected_tags)}" if match == "all" else ""
                selected_rows = f"SELECT source_id, record_index, MAX(event_date) AS event_date FROM source_record_tags WHERE {' AND '.join(row_conditions)} GROUP BY source_id, record_index{having} ORDER BY event_date DESC, source_id, record_index DESC LIMIT ? OFFSET ?"
            else:
                selected_date = "MAX(tag_filter.event_date)" if len(selected_tags) > 1 else "tag_filter.event_date"
                selected_rows = f"SELECT r.source_id, r.record_index, {selected_date} AS event_date {from_clause} {where} {group_clause} ORDER BY {order} LIMIT ? OFFSET ?"
                row_params = params
            rows = self.connection.execute(
                f"SELECT r.source_id, f.path, f.kind, r.record_index, r.event_date, r.title, r.payload_json, (SELECT GROUP_CONCAT(t.tag, char(31)) FROM source_record_tags t WHERE t.source_id=r.source_id AND t.record_index=r.record_index) FROM ({selected_rows}) selected JOIN source_records r ON r.source_id=selected.source_id AND r.record_index=selected.record_index JOIN source_files f ON f.id=r.source_id ORDER BY selected.event_date DESC, selected.source_id, selected.record_index DESC",
                (*row_params, limit, offset),
            ).fetchall()
        else:
            rows = self.connection.execute(
                f"SELECT r.source_id, f.path, f.kind, r.record_index, r.event_date, r.title, r.payload_json, (SELECT GROUP_CONCAT(t.tag, char(31)) FROM source_record_tags t WHERE t.source_id=r.source_id AND t.record_index=r.record_index) {from_clause} {where} {group_clause} ORDER BY {order} LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return {"total": total, "offset": offset, "limit": limit, "items": [{"source_id": row[0], "source_path": row[1], "kind": row[2], "record_index": row[3], "event_date": row[4], "title": row[5], "payload": json.loads(row[6]), "tags": row[7].split(chr(31)) if row[7] else []} for row in rows]}

    @synchronized
    def close(self) -> None:
        self.connection.close()
