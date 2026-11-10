from __future__ import annotations

import json
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.auth import AuthStore
from app.core.config import load_config
from app.services.audit_archive import AuditArchiveManager
from app.services.catalog_factory import create_catalog
from app.services.object_archive import ObjectArchive


def cache_acceptance() -> dict:
    first = create_catalog(load_config())
    second = create_catalog(load_config())
    try:
        expected = first.summary()
        assert first.summary() == expected
        assert second.summary() == expected
        assert second.summary() == expected
        first_stats = first.cache_stats
        second_stats = second.cache_stats
        assert first_stats["local"]["hits"] >= 1
        assert second_stats["shared"]["hits"] >= 1
        assert second_stats["local"]["hits"] >= 1
        return {"passed": True, "records": expected["total_records"], "first_instance": first_stats, "second_instance": second_stats}
    finally:
        first.close()
        second.close()


def audit_acceptance() -> dict:
    config = load_config()
    bucket = f"marketlens-audit-acceptance-{uuid.uuid4().hex[:12]}"
    archive = ObjectArchive.from_config({**config.minio, "bucket": bucket})
    key = None
    try:
        with tempfile.TemporaryDirectory(prefix="marketlens-audit-") as directory:
            store = AuthStore(Path(directory) / "auth.sqlite3")
            for index in range(250):
                store.record_event("acceptance", "replay_pause", f"synthetic-{index}", 200)
            with store.connect() as db:
                db.execute("UPDATE auth_audit SET occurred=1")
            manager = AuditArchiveManager(store, archive, retention_days=1, online_min_records=100)
            result = manager.archive_expired()
            assert result["archived"] == 150
            key = result["archive"]["object_key"]
            assert manager.overview()["online_records"] == 100
            verified = manager.verify(result["archive"]["id"])
            records = manager.records(result["archive"]["id"])
            assert len(records["items"]) == 150
            return {"passed": True, "temporary_identity": True, "archived": result["archived"], "online_retained": 100, "verified": verified, "object_removed_after_test": True}
    finally:
        if key:
            archive.client.remove_object(bucket, key)
        if archive.client.bucket_exists(bucket) and not list(archive.client.list_objects(bucket)):
            archive.client.remove_bucket(bucket)


def main():
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "cache": cache_acceptance(), "audit_archive": audit_acceptance()}
    output = Path(__file__).resolve().parents[1] / "data" / "benchmarks" / f"supplemental-governance-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "report": str(output), "cache": report["cache"]["passed"], "audit_archive": report["audit_archive"]["passed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
