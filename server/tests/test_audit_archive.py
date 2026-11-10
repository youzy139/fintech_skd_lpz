from __future__ import annotations

import json

import pytest

from app.core.auth import AuthStore
from app.services.audit_archive import AuditArchiveManager
from test_auth import bearer, bootstrap, create_user, secured


class FakeObjects:
    def __init__(self):
        self.bucket = "test-audit"
        self.values = {}
        self.fail = False

    def put_bytes(self, key, payload, content_type="application/x-ndjson"):
        if self.fail:
            raise OSError("offline")
        self.values[key] = payload

    def get_bytes(self, key):
        return self.values[key]


def old_events(store, count):
    for index in range(count):
        store.record_event("owner", "replay_pause", f"session-{index}", 200)
    with store.connect() as db:
        db.execute("UPDATE auth_audit SET occurred=1")


def test_archive_retention_round_trip_and_tamper_detection(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    objects = FakeObjects()
    old_events(store, 250)
    manager = AuditArchiveManager(store, objects, retention_days=1, online_min_records=100)
    result = manager.archive_expired()
    assert result["archived"] == 150
    assert manager.overview()["online_records"] == 100
    identifier = result["archive"]["id"]
    verified = manager.verify(identifier)
    assert verified["verified"] and verified["record_count"] == 150
    archived = manager.records(identifier)
    assert len(archived["items"]) == 150
    assert archived["items"][0]["target"] == "session-149"
    assert "password" not in json.dumps(archived)
    assert manager.archive_expired()["archived"] == 0
    objects.values[result["archive"]["object_key"]] += b"tampered"
    with pytest.raises(ValueError, match="SHA-256"):
        manager.verify(identifier)
    assert store.audit_archive(identifier)["verification"] == "failed"


def test_failed_upload_never_deletes_online_audit(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    objects = FakeObjects()
    old_events(store, 150)
    objects.fail = True
    manager = AuditArchiveManager(store, objects, retention_days=1, online_min_records=100)
    with pytest.raises(OSError):
        manager.archive_expired()
    assert manager.overview()["online_records"] == 150
    assert manager.overview()["archives"] == []


def test_archive_api_is_admin_only_and_reads_verified_records(secured, monkeypatch):
    client, store, code = secured
    bootstrap(client, code)
    old_events(store, 150)
    manager = AuditArchiveManager(store, FakeObjects(), retention_days=1, online_min_records=100)
    monkeypatch.setattr("app.api.auth.audit_archive", lambda: manager)
    observer = bearer(create_user(store))
    assert client.get("/api/auth/audit/overview", headers=observer).status_code == 403
    overview = client.get("/api/auth/audit/overview").json()
    assert overview["policy"]["online_min_records"] == 100
    origin = {"Origin": "http://localhost:5173"}
    assert client.post("/api/auth/audit/archive", headers=origin).json()["archived"] >= 50
    archive = client.get("/api/auth/audit/overview").json()["archives"][0]
    identifier = archive["id"]
    assert client.post(f"/api/auth/audit/archives/{identifier}/verify", headers=origin).json()["verified"]
    records = client.get(f"/api/auth/audit/archives/{identifier}/records").json()
    assert records["items"] and set(records["items"][0]) == {"id", "occurred", "actor", "action", "target", "request_id", "status"}
    assert client.post("/api/auth/audit/archives/missing/verify", headers=origin).status_code == 404
