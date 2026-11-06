from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


class ReplayStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = RLock()
        with self.lock, self.connection:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS replay_sessions (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    speed REAL NOT NULL,
                    position INTEGER NOT NULL,
                    run_id TEXT,
                    flink_job_id TEXT,
                    savepoint_path TEXT,
                    recovery_state TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_results (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_date TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS replay_results_session_date
                    ON replay_results (session_id, event_date);
                CREATE TABLE IF NOT EXISTS replay_operations (
                    session_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, action, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS replay_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_owners (
                    session_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL
                );
            """)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _save_session(self, snapshot: dict[str, Any]) -> None:
        now = self._now()
        recovery = snapshot.get("recovery", {})
        self.connection.execute("""
            INSERT INTO replay_sessions (
                id, mode, status, start_date, end_date, speed, position, run_id,
                flink_job_id, savepoint_path, recovery_state, snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                mode = excluded.mode,
                status = excluded.status,
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                speed = excluded.speed,
                position = excluded.position,
                run_id = excluded.run_id,
                flink_job_id = excluded.flink_job_id,
                savepoint_path = excluded.savepoint_path,
                recovery_state = excluded.recovery_state,
                snapshot_json = excluded.snapshot_json,
                updated_at = excluded.updated_at
        """, (
            snapshot["id"], snapshot["mode"], snapshot["status"], snapshot["start_date"], snapshot["end_date"],
            snapshot["speed"], snapshot["processed_days"], snapshot.get("run_id"), snapshot.get("flink_job_id"),
            snapshot.get("savepoint_path"), recovery.get("state", "none"), self._json(snapshot), now, now,
        ))

    def claim(self, session_id: str, token: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO replay_owners VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET token = excluded.token", (session_id, token))

    def owns(self, session_id: str, token: str) -> bool:
        with self.lock:
            row = self.connection.execute("SELECT token FROM replay_owners WHERE session_id = ?", (session_id,)).fetchone()
        return bool(row and row["token"] == token)

    def _guard(self, session_id: str, token: str | None) -> None:
        from app.services.replay_capacity import ReplayLeaseLost

        # Take SQLite's writer lock before checking the token. The ownership
        # check and subsequent result/snapshot write share one transaction.
        self.connection.execute("UPDATE replay_owners SET token = token WHERE session_id = ?", (session_id,))
        row = self.connection.execute("SELECT token FROM replay_owners WHERE session_id = ?", (session_id,)).fetchone()
        if row and row["token"] != token:
            raise ReplayLeaseLost("回放执行权已转移，请刷新会话后重试")

    def save_session(self, snapshot: dict[str, Any], owner: str | None = None) -> None:
        with self.lock, self.connection:
            self._guard(snapshot["id"], owner)
            self._save_session(snapshot)

    def record_result(self, snapshot: dict[str, Any], sequence: int, result: dict[str, Any], owner: str | None = None) -> None:
        with self.lock, self.connection:
            self._guard(snapshot["id"], owner)
            self.connection.execute("""
                INSERT INTO replay_results (session_id, sequence, event_date, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, sequence) DO NOTHING
            """, (snapshot["id"], sequence, result["event_time"], self._json(result), self._now()))
            self._save_session(snapshot)

    def reset_session(self, snapshot: dict[str, Any], owner: str | None = None) -> None:
        with self.lock, self.connection:
            self._guard(snapshot["id"], owner)
            self.connection.execute("DELETE FROM replay_results WHERE session_id = ?", (snapshot["id"],))
            self._save_session(snapshot)

    def load_sessions(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute("SELECT * FROM replay_sessions ORDER BY updated_at").fetchall()
        return [{**json.loads(row["snapshot_json"]), "stored_position": row["position"], "stored_status": row["status"]} for row in rows]

    def results(self, session_id: str, after: int = 0, limit: int = 100) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, 100))
        with self.lock:
            rows = self.connection.execute("""
                SELECT sequence, event_date, result_json FROM replay_results
                WHERE session_id = ? AND sequence > ? ORDER BY sequence LIMIT ?
            """, (session_id, after, bounded_limit + 1)).fetchall()
        items = [{"sequence": row["sequence"], "event_date": row["event_date"], "result": json.loads(row["result_json"])} for row in rows[:bounded_limit]]
        next_sequence = items[-1]["sequence"] if items else after
        return {"session_id": session_id, "results": items, "next_sequence": next_sequence, "has_more": len(rows) > bounded_limit}

    def latest_result(self, session_id: str) -> tuple[int, dict[str, Any]] | None:
        with self.lock:
            row = self.connection.execute("""
                SELECT sequence, result_json FROM replay_results
                WHERE session_id = ? ORDER BY sequence DESC LIMIT 1
            """, (session_id,)).fetchone()
        return (row["sequence"], json.loads(row["result_json"])) if row else None

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute("SELECT snapshot_json, position, status FROM replay_sessions WHERE id = ?", (session_id,)).fetchone()
        return {**json.loads(row["snapshot_json"]), "stored_position": row["position"], "stored_status": row["status"]} if row else None

    def set_current(self, session_id: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO replay_metadata (key, value) VALUES ('current_session_id', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (session_id,))

    def current_id(self) -> str | None:
        with self.lock:
            row = self.connection.execute("SELECT value FROM replay_metadata WHERE key = 'current_session_id'").fetchone()
        return row["value"] if row else None

    def operation(self, session_id: str, action: str, key: str | None, request: dict[str, Any]) -> dict[str, Any] | None:
        if not key:
            return None
        with self.lock:
            row = self.connection.execute("""
                SELECT request_json, snapshot_json FROM replay_operations
                WHERE session_id = ? AND action = ? AND idempotency_key = ?
            """, (session_id, action, key)).fetchone()
        if not row:
            return None
        if json.loads(row["request_json"]) != request:
            raise ValueError("同一幂等键不能用于不同请求")
        return json.loads(row["snapshot_json"])

    def save_operation(self, session_id: str, action: str, key: str | None, request: dict[str, Any], snapshot: dict[str, Any], owner: str | None = None) -> None:
        if not key:
            return
        with self.lock, self.connection:
            self._guard(session_id, owner)
            self.connection.execute("""
                INSERT INTO replay_operations (session_id, action, idempotency_key, request_json, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, action, idempotency_key) DO NOTHING
            """, (session_id, action, key, self._json(request), self._json(snapshot), self._now()))

    def close(self) -> None:
        with self.lock:
            self.connection.close()
