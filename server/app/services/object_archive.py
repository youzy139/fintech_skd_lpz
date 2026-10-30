from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path, PurePosixPath
from typing import Any

from minio import Minio
from minio.error import S3Error

from market_core.domain.sources import SourceFile


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def source_object_key(source: SourceFile, sha256: str) -> str:
    filename = PurePosixPath(source.path).name
    return f"raw/{source.id}/{sha256}/{filename}"


class ObjectArchive:
    def __init__(self, client: Any, bucket: str):
        self.client = client
        self.bucket = bucket
        self._bucket_ready = False

    @classmethod
    def from_config(cls, settings: dict[str, Any]) -> ObjectArchive:
        client = Minio(
            settings["endpoint"],
            access_key=settings["access_key"],
            secret_key=settings["secret_key"],
            secure=bool(settings.get("secure", False)),
        )
        return cls(client, settings["bucket"])

    def _ensure_bucket(self) -> None:
        if not self._bucket_ready:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            self._bucket_ready = True

    def archive(self, source: SourceFile) -> dict[str, Any]:
        self._ensure_bucket()
        stat = source.absolute_path.stat()
        if stat.st_size != source.size or stat.st_mtime_ns != source.mtime_ns:
            raise ValueError(f"文件在归档前已变化：{source.path}")
        sha256 = file_sha256(source.absolute_path)
        stat_after = source.absolute_path.stat()
        if stat_after.st_size != source.size or stat_after.st_mtime_ns != source.mtime_ns:
            raise ValueError(f"文件在哈希读取期间发生变化：{source.path}")
        key = source_object_key(source, sha256)
        try:
            object_stat = self.client.stat_object(self.bucket, key)
            if object_stat.size != source.size:
                raise ValueError(f"对象大小与来源文件不一致：{source.path}")
            uploaded = False
        except S3Error as error:
            if error.code not in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                raise
            result = self.client.fput_object(
                self.bucket,
                key,
                str(source.absolute_path),
                content_type=mimetypes.guess_type(source.path)[0] or "application/octet-stream",
            )
            object_stat = self.client.stat_object(self.bucket, key)
            if object_stat.size != source.size:
                raise ValueError(f"上传后对象大小不一致：{source.path}")
            uploaded = True
        return {
            "source_id": source.id,
            "bucket": self.bucket,
            "key": key,
            "sha256": sha256,
            "size": source.size,
            "etag": getattr(object_stat, "etag", None) if not uploaded else result.etag,
            "version_id": getattr(object_stat, "version_id", None) if not uploaded else result.version_id,
            "uploaded": uploaded,
        }

    def verify(self, source: SourceFile, metadata: dict[str, Any]) -> dict[str, Any]:
        local_sha256 = file_sha256(source.absolute_path)
        if metadata["sha256"] != local_sha256 or int(metadata["size"]) != source.size:
            raise ValueError(f"对象元数据与本地文件不一致：{source.path}")
        response = self.client.get_object(metadata["bucket"], metadata["key"])
        digest = hashlib.sha256()
        size = 0
        try:
            for chunk in response.stream(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        finally:
            response.close()
            response.release_conn()
        if size != source.size or digest.hexdigest() != local_sha256:
            raise ValueError(f"对象回读校验失败：{source.path}")
        return {"source_id": source.id, "size": size, "sha256": local_sha256, "verified": True}
