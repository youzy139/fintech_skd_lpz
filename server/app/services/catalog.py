from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from market_core.domain.sources import SourceFile, SourceRecord
from market_core.ingestion.sources import iter_records, source_sheets


class CatalogStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
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
                event_date TEXT, title TEXT NOT NULL, payload_json TEXT NOT NULL,
                PRIMARY KEY (source_id, record_index)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_records_date ON source_records(event_date);
            CREATE INDEX IF NOT EXISTS idx_records_title ON source_records(title);
            CREATE INDEX IF NOT EXISTS idx_files_kind ON source_files(kind);
            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
                status TEXT NOT NULL, record_count INTEGER NOT NULL DEFAULT 0,
                error TEXT, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            );
            """
        )

    def is_unchanged(self, source: SourceFile) -> bool:
        row = self.connection.execute("SELECT 1 FROM source_files WHERE id = ? AND size = ? AND mtime_ns = ? AND status = 'imported'", (source.id, source.size, source.mtime_ns)).fetchone()
        return row is not None

    def import_file(self, source: SourceFile, batch_size: int = 1000) -> dict[str, Any]:
        cursor = self.connection.execute("INSERT INTO import_batches (source_id, status) VALUES (?, 'running')", (source.id,))
        batch_id = cursor.lastrowid
        self.connection.execute(
            "INSERT INTO source_files (id, kind, path, size, mtime_ns, status) VALUES (?, ?, ?, ?, ?, 'importing') ON CONFLICT(id) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, status='importing', error=NULL",
            (source.id, source.kind, source.path, source.size, source.mtime_ns),
        )
        self.connection.execute("DELETE FROM source_records WHERE source_id = ?", (source.id,))
        self.connection.commit()
        count = 0
        try:
            batch: list[tuple] = []
            for record in iter_records(source):
                batch.append(self._record_tuple(record))
                if len(batch) >= batch_size:
                    self._write_batch(batch)
                    count += len(batch)
                    batch = []
            if batch:
                self._write_batch(batch)
                count += len(batch)
            sheets = source_sheets(source)
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
    def _record_tuple(record: SourceRecord) -> tuple:
        return (record.source_id, record.record_index, record.event_date, record.title, json.dumps(record.payload, ensure_ascii=False, default=str))

    def _write_batch(self, batch: Iterable[tuple]) -> None:
        self.connection.executemany("INSERT INTO source_records (source_id, record_index, event_date, title, payload_json) VALUES (?, ?, ?, ?, ?)", batch)
        self.connection.commit()

    def summary(self) -> dict[str, Any]:
        row = self.connection.execute("SELECT COUNT(*), COALESCE(SUM(status='imported'),0), COALESCE(SUM(record_count),0), COALESCE(SUM(error_count),0) FROM source_files").fetchone()
        groups = self.connection.execute("SELECT kind, COUNT(*), COALESCE(SUM(record_count),0) FROM source_files GROUP BY kind ORDER BY kind").fetchall()
        return {"total_files": row[0], "imported_files": row[1], "total_records": row[2], "errors": row[3], "groups": [{"kind": item[0], "files": item[1], "records": item[2]} for item in groups]}

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

    def list_records(self, source_id: str, query: str | None, date: str | None, offset: int, limit: int) -> dict[str, Any]:
        conditions = ["source_id = ?"]
        params: list[Any] = [source_id]
        if query:
            conditions.append("title LIKE ?")
            params.append(f"%{query}%")
        if date:
            conditions.append("event_date = ?")
            params.append(date)
        where = " AND ".join(conditions)
        total = self.connection.execute(f"SELECT COUNT(*) FROM source_records WHERE {where}", params).fetchone()[0]
        rows = self.connection.execute(f"SELECT record_index, event_date, title, payload_json FROM source_records WHERE {where} ORDER BY record_index LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return {"total": total, "offset": offset, "limit": limit, "items": [{"record_index": row[0], "event_date": row[1], "title": row[2], "payload": json.loads(row[3])} for row in rows]}

    def close(self) -> None:
        self.connection.close()
