from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_core.models.alerts import alert_rule_version, normalize_rule_settings


class AlertRuleManager:
    def __init__(self, database_path: str | Path, defaults: dict[str, Any]):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.defaults = normalize_rule_settings(defaults)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS alert_rule_versions (
                    version TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_rule_state (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    active_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
            """)
            initialized = db.execute("SELECT 1 FROM alert_rule_state WHERE id = 1").fetchone()
        if not initialized:
            self.save(self.defaults, "system")

    def connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _version(row: sqlite3.Row, active_version: str) -> dict[str, Any]:
        return {
            "version": row["version"],
            "settings": json.loads(row["settings_json"]),
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "active": row["version"] == active_version,
        }

    def current(self) -> dict[str, Any]:
        with self.connect() as db:
            active = db.execute("SELECT active_version FROM alert_rule_state WHERE id = 1").fetchone()
            row = db.execute("SELECT * FROM alert_rule_versions WHERE version = ?", (active["active_version"],)).fetchone()
            return self._version(row, active["active_version"])

    def describe(self) -> dict[str, Any]:
        current = self.current()
        with self.connect() as db:
            rows = db.execute("SELECT * FROM alert_rule_versions ORDER BY created_at DESC, version DESC").fetchall()
            return {"active": current, "versions": [self._version(row, current["version"]) for row in rows]}

    def save(self, settings: dict[str, Any], actor: str) -> dict[str, Any]:
        normalized = normalize_rule_settings(settings)
        version = alert_rule_version(normalized)
        now = self._now()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO alert_rule_versions VALUES (?, ?, ?, ?)", (version, json.dumps(normalized, sort_keys=True), now, actor))
            db.execute("INSERT INTO alert_rule_state VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET active_version=excluded.active_version, updated_at=excluded.updated_at, updated_by=excluded.updated_by", (version, now, actor))
        return self.current()

    def activate(self, version: str, actor: str) -> dict[str, Any]:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM alert_rule_versions WHERE version = ?", (version,)).fetchone():
                raise KeyError(version)
            db.execute("UPDATE alert_rule_state SET active_version=?, updated_at=?, updated_by=? WHERE id=1", (version, self._now(), actor))
        return self.current()
