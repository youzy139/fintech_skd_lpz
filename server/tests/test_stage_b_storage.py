from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from minio.error import S3Error

from app.services.mysql_metadata import MySQLMetadataStore, sql_statements
from app.services.object_archive import ObjectArchive, file_sha256, source_object_key
from market_core.domain.sources import SourceFile


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.closed = False

    def stream(self, chunk_size: int):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def close(self):
        self.closed = True

    def release_conn(self):
        pass


class FakeMinio:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.uploads = 0

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def make_bucket(self, bucket: str):
        pass

    def stat_object(self, bucket: str, key: str):
        if (bucket, key) not in self.objects:
            raise S3Error(None, "NoSuchKey", "missing", key, "request", "host")
        return SimpleNamespace(size=len(self.objects[bucket, key]), etag="etag", version_id=None)

    def fput_object(self, bucket: str, key: str, path: str, content_type: str):
        self.uploads += 1
        self.objects[bucket, key] = Path(path).read_bytes()
        return SimpleNamespace(etag="etag", version_id=None)

    def get_object(self, bucket: str, key: str):
        return FakeResponse(self.objects[bucket, key])


def make_source(tmp_path: Path) -> SourceFile:
    path = tmp_path / "原始文件.csv"
    path.write_bytes("日期,数值\n2024-01-01,1\n".encode("utf-8"))
    return SourceFile.create(tmp_path, path, "indicator")


def test_mysql_migration_parser_and_database_name_validation():
    script = "-- comment\nCREATE TABLE a (id INT);\n\nCREATE TABLE b (id INT);"
    assert sql_statements(script) == ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"]
    with pytest.raises(ValueError, match="数据库名"):
        MySQLMetadataStore({"database": "marketlens;DROP DATABASE mysql"})


def test_archive_is_immutable_repeatable_and_verifies_round_trip(tmp_path: Path):
    source = make_source(tmp_path)
    client = FakeMinio()
    archive = ObjectArchive(client, "raw")
    first = archive.archive(source)
    second = archive.archive(source)
    assert first["uploaded"] is True
    assert second["uploaded"] is False
    assert client.uploads == 1
    assert first["key"] == second["key"] == source_object_key(source, file_sha256(source.absolute_path))
    assert archive.verify(source, first) == {"source_id": source.id, "size": source.size, "sha256": first["sha256"], "verified": True}


def test_archive_detects_local_change_and_remote_corruption(tmp_path: Path):
    source = make_source(tmp_path)
    client = FakeMinio()
    archive = ObjectArchive(client, "raw")
    metadata = archive.archive(source)
    client.objects[metadata["bucket"], metadata["key"]] = b"corrupted"
    with pytest.raises(ValueError, match="回读校验失败"):
        archive.verify(source, metadata)
    source.absolute_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="归档前已变化"):
        archive.archive(source)


def test_archive_rejects_mismatched_metadata(tmp_path: Path):
    source = make_source(tmp_path)
    archive = ObjectArchive(FakeMinio(), "raw")
    metadata = archive.archive(source)
    with pytest.raises(ValueError, match="元数据"):
        archive.verify(source, {**metadata, "sha256": "0" * 64})
