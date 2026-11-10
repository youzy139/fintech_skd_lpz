from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.auth import AuthStore, auth_store
from app.core.config import load_config
from app.services.object_archive import ObjectArchive


class AuditArchiveManager:
    def __init__(self, store: AuthStore, archive: ObjectArchive | None, retention_days: int | None = None, online_min_records: int | None = None):
        self.store = store
        self.archive = archive
        self.retention_days = retention_days or int(os.getenv("AUDIT_RETENTION_DAYS", "90"))
        self.online_min_records = online_min_records or int(os.getenv("AUDIT_ONLINE_MIN_RECORDS", "10000"))
        if not 1 <= self.retention_days <= 3650 or not 100 <= self.online_min_records <= 1000000:
            raise ValueError("审计保留参数超出允许范围")

    def overview(self) -> dict[str, Any]:
        with self.store.connect() as db:
            online = db.execute("SELECT count(*) FROM auth_audit").fetchone()[0]
        return {
            "enabled": self.archive is not None,
            "policy": {"retention_days": self.retention_days, "online_min_records": self.online_min_records, "batch_limit": 5000},
            "online_records": online,
            "archives": self.store.audit_archives(),
        }

    def archive_expired(self) -> dict[str, Any]:
        if self.archive is None:
            raise RuntimeError("未启用 MinIO，审计仍只保留在在线身份库")
        cutoff = int(time.time()) - self.retention_days * 86400
        rows = self.store.archive_candidates(cutoff, self.online_min_records)
        if not rows:
            return {"archived": 0, "reason": "没有同时满足到期时间和在线保留下限的记录"}
        payload = b"".join((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8") for row in rows)
        digest = hashlib.sha256(payload).hexdigest()
        day = datetime.fromtimestamp(rows[-1]["occurred"], timezone.utc).strftime("%Y/%m/%d")
        metadata = {
            "id": digest,
            "first_id": rows[0]["id"],
            "last_id": rows[-1]["id"],
            "first_occurred": rows[0]["occurred"],
            "last_occurred": rows[-1]["occurred"],
            "record_count": len(rows),
            "sha256": digest,
            "size": len(payload),
            "bucket": self.archive.bucket,
            "object_key": f"audit/{day}/{rows[0]['id']}-{rows[-1]['id']}-{digest[:16]}.jsonl",
            "created": int(time.time()),
        }
        self.archive.put_bytes(metadata["object_key"], payload)
        self.store.commit_archive(metadata, [row["id"] for row in rows])
        return {"archived": len(rows), "archive": self.store.audit_archive(digest)}

    def _read(self, identifier: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self.archive is None:
            raise RuntimeError("未启用审计对象归档")
        metadata = self.store.audit_archive(identifier)
        payload = self.archive.get_bytes(metadata["object_key"])
        if len(payload) != metadata["size"] or hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
            raise ValueError("审计归档的大小或 SHA-256 校验不一致")
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
        if len(rows) != metadata["record_count"] or not rows or rows[0]["id"] != metadata["first_id"] or rows[-1]["id"] != metadata["last_id"]:
            raise ValueError("审计归档的记录数或边界不一致")
        return metadata, rows

    def verify(self, identifier: str) -> dict[str, Any]:
        try:
            metadata, rows = self._read(identifier)
        except Exception:
            self.store.record_archive_verification(identifier, int(time.time()), "failed")
            raise
        self.store.record_archive_verification(identifier, int(time.time()), "verified")
        return {"id": identifier, "verified": True, "record_count": len(rows), "sha256": metadata["sha256"], "verified_at": int(time.time())}

    def records(self, identifier: str) -> dict[str, Any]:
        metadata, rows = self._read(identifier)
        return {"archive": metadata, "items": list(reversed(rows))}


@lru_cache(maxsize=4)
def archive_for(path: str) -> AuditArchiveManager:
    config = load_config()
    archive = ObjectArchive.from_config(config.minio) if config.minio.get("enabled", False) else None
    return AuditArchiveManager(AuthStore(path=Path(path)), archive)


def audit_archive() -> AuditArchiveManager:
    store = auth_store()
    return archive_for(str(store.path.resolve()))
