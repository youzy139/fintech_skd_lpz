from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class SnapshotStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    def save(self, key: str, value: object) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        self.connection.execute("INSERT INTO snapshots (key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = CURRENT_TIMESTAMP", (key, payload))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
