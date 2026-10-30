from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pymysql

from app.core.config import SERVER_ROOT
from app.services.catalog import CatalogStore


def sql_statements(script: str) -> list[str]:
    lines = [line for line in script.splitlines() if not line.lstrip().startswith("--")]
    return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]


class MySQLMetadataStore:
    def __init__(self, settings: dict[str, Any], migrations_path: Path | None = None):
        self.settings = settings
        self.migrations_path = migrations_path or SERVER_ROOT / "migrations" / "mysql"
        if not re.fullmatch(r"[A-Za-z0-9_]+", settings["database"]):
            raise ValueError("MySQL 数据库名只能包含字母、数字和下划线")

    @contextmanager
    def connection(self, database: bool = True) -> Iterator[Any]:
        connection = pymysql.connect(
            host=self.settings["host"],
            port=int(self.settings["port"]),
            user=self.settings["user"],
            password=self.settings["password"],
            database=self.settings["database"] if database else None,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=5,
            read_timeout=30,
            write_timeout=60,
        )
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> list[str]:
        with self.connection(database=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.settings['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            connection.commit()
        applied = []
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)) ENGINE=InnoDB")
                connection.commit()
                for path in sorted(self.migrations_path.glob("*.sql")):
                    version = path.stem
                    cursor.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
                    if cursor.fetchone():
                        continue
                    for statement in sql_statements(path.read_text(encoding="utf-8")):
                        cursor.execute(statement)
                    cursor.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                    connection.commit()
                    applied.append(version)
        return applied

    def migrate_from(self, catalog: CatalogStore) -> dict[str, int]:
        files = catalog.connection.execute(
            "SELECT id, kind, path, size, mtime_ns, status, record_count, error_count, sheets_json, error, updated_at FROM source_files ORDER BY id"
        ).fetchall()
        batches = catalog.connection.execute(
            "SELECT id, source_id, status, record_count, error, started_at, completed_at FROM import_batches ORDER BY id"
        ).fetchall()
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO source_files (id, kind, path, path_sha256, size, mtime_ns, status, record_count, error_count, sheets_json, error, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE kind=VALUES(kind), path=VALUES(path), path_sha256=VALUES(path_sha256), size=VALUES(size),
                        mtime_ns=VALUES(mtime_ns), status=VALUES(status), record_count=VALUES(record_count), error_count=VALUES(error_count),
                        sheets_json=VALUES(sheets_json), error=VALUES(error), updated_at=VALUES(updated_at)
                    """,
                    [(*row[:3], hashlib.sha256(row[2].encode("utf-8")).hexdigest(), *row[3:]) for row in files],
                )
                cursor.executemany(
                    """
                    INSERT INTO import_batches (id, source_id, status, record_count, error, started_at, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE source_id=VALUES(source_id), status=VALUES(status), record_count=VALUES(record_count),
                        error=VALUES(error), started_at=VALUES(started_at), completed_at=VALUES(completed_at)
                    """,
                    batches,
                )
            connection.commit()
        return {"files": len(files), "import_batches": len(batches)}

    def list_files(self, kind: str | None = None, query: str | None = None, offset: int = 0, limit: int = 100000) -> dict[str, Any]:
        conditions = []
        params: list[Any] = []
        if kind:
            conditions.append("kind = %s")
            params.append(kind)
        if query:
            conditions.append("path LIKE %s")
            params.append(f"%{query}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM source_files {where}", params)
                total = cursor.fetchone()[0]
                cursor.execute(
                    f"SELECT id, kind, path, status, record_count, error_count, sheets_json, error, size, mtime_ns FROM source_files {where} ORDER BY kind, path LIMIT %s OFFSET %s",
                    (*params, limit, offset),
                )
                rows = cursor.fetchall()
        return {"total": total, "offset": offset, "limit": limit, "items": [self._file_dict(row) for row in rows]}

    @staticmethod
    def _file_dict(row: tuple) -> dict[str, Any]:
        sheets = row[6] if isinstance(row[6], str) else json.dumps(row[6])
        return {"id": row[0], "kind": row[1], "path": row[2], "status": row[3], "record_count": row[4], "error_count": row[5], "sheets": json.loads(sheets), "error": row[7], "size": row[8], "mtime_ns": row[9]}

    def summary(self) -> dict[str, Any]:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*), COALESCE(SUM(status='imported'),0), COALESCE(SUM(record_count),0), COALESCE(SUM(error_count),0) FROM source_files")
                row = cursor.fetchone()
                cursor.execute("SELECT kind, COUNT(*), COALESCE(SUM(record_count),0) FROM source_files GROUP BY kind ORDER BY kind")
                groups = cursor.fetchall()
        return {"total_files": int(row[0]), "imported_files": int(row[1]), "total_records": int(row[2]), "errors": int(row[3]), "groups": [{"kind": item[0], "files": int(item[1]), "records": int(item[2])} for item in groups]}

    def register_object(self, source_id: str, bucket: str, key: str, sha256: str, size: int, etag: str | None, version_id: str | None = None) -> None:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO source_objects (source_id, bucket_name, object_key, sha256, size, etag, version_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE bucket_name=VALUES(bucket_name), object_key=VALUES(object_key), size=VALUES(size),
                        etag=VALUES(etag), version_id=VALUES(version_id), archived_at=CURRENT_TIMESTAMP(6)
                    """,
                    (source_id, bucket, key, sha256, size, etag, version_id),
                )
            connection.commit()

    def object_for_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT bucket_name, object_key, sha256, size, etag, version_id FROM source_objects WHERE source_id = %s ORDER BY id DESC LIMIT 1", (source_id,))
                row = cursor.fetchone()
        if not row:
            return None
        return {"bucket": row[0], "key": row[1], "sha256": row[2], "size": row[3], "etag": row[4], "version_id": row[5]}

    def object_count(self) -> int:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM source_objects")
                return cursor.fetchone()[0]

    def verify_against(self, catalog: CatalogStore) -> list[str]:
        differences = []
        expected_summary = catalog.summary()
        actual_summary = self.summary()
        if expected_summary != actual_summary:
            differences.append(f"summary: {expected_summary!r} != {actual_summary!r}")
        expected_files = catalog.list_files(None, None, 0, 100000)["items"]
        actual_files = self.list_files()["items"]
        if expected_files != actual_files:
            differences.append("source_files: 文件元数据与 SQLite 不一致")
        return differences
