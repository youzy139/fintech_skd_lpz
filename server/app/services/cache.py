from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

import redis
from redis.exceptions import RedisError

from app.services.contracts import CatalogStorage
from market_core.domain.sources import SourceFile


class RedisJsonCache:
    def __init__(self, client: Any, namespace: str, ttl_seconds: int):
        if ttl_seconds < 1:
            raise ValueError("缓存 TTL 必须大于 0 秒")
        self.client = client
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self.stats = {"hits": 0, "misses": 0, "writes": 0, "errors": 0}

    @classmethod
    def from_config(cls, settings: dict[str, Any]) -> RedisJsonCache:
        client = redis.Redis(
            host=settings["host"],
            port=int(settings["port"]),
            db=int(settings["db"]),
            password=settings["password"] or None,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        return cls(client, settings["namespace"], int(settings["ttl_seconds"]))

    def get(self, key: str) -> Any | None:
        try:
            value = self.client.get(key)
            if value is None:
                self.stats["misses"] += 1
                return None
            self.stats["hits"] += 1
            return json.loads(value)
        except (RedisError, TypeError, ValueError):
            self.stats["errors"] += 1
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self.client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=self.ttl_seconds)
            self.stats["writes"] += 1
        except (RedisError, TypeError, ValueError):
            self.stats["errors"] += 1

    def close(self) -> None:
        self.client.close()


class CachedCatalogStore:
    def __init__(self, delegate: CatalogStorage, cache: RedisJsonCache):
        self.delegate = delegate
        self.cache = cache

    @property
    def cache_stats(self) -> dict[str, Any]:
        return {**self.cache.stats, "namespace": self.cache.namespace, "ttl_seconds": self.cache.ttl_seconds}

    def data_version(self) -> str:
        return self.delegate.data_version()

    def _cached(self, method: str, arguments: Any, loader: Callable[[], Any]) -> Any:
        identity = json.dumps([self.cache.namespace, self.data_version(), method, arguments], ensure_ascii=False, sort_keys=True, default=str)
        key = self.cache.namespace + ":" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        result = loader()
        self.cache.set(key, result)
        return result

    def summary(self) -> dict[str, Any]:
        return self._cached("summary", None, self.delegate.summary)

    def overview(self, kind: str | None) -> dict[str, Any]:
        return self._cached("overview", kind, lambda: self.delegate.overview(kind))

    def list_tags(self, kind: str | None) -> list[dict[str, Any]]:
        return self._cached("tags", kind, lambda: self.delegate.list_tags(kind))

    def list_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        if offset != 0 or limit > 100:
            return self.delegate.list_files(kind, query, offset, limit)
        return self._cached("files", [kind, query, limit], lambda: self.delegate.list_files(kind, query, offset, limit))

    def list_records(self, source_id: str | None, query: str | None, date: str | None, offset: int, limit: int, kind: str | None = None, tag: str | None = None, tags: list[str] | None = None, match: str = "any") -> dict[str, Any]:
        if offset != 0 or limit > 100:
            return self.delegate.list_records(source_id, query, date, offset, limit, kind, tag, tags, match)
        arguments = [source_id, query, date, limit, kind, tag, tags, match]
        return self._cached("records", arguments, lambda: self.delegate.list_records(source_id, query, date, offset, limit, kind, tag, tags, match))

    def is_unchanged(self, source: SourceFile) -> bool:
        return self.delegate.is_unchanged(source)

    def import_file(self, source: SourceFile, batch_size: int = 1000) -> dict[str, Any]:
        return self.delegate.import_file(source, batch_size)

    def rebuild_statistics(self) -> dict[str, int]:
        return self.delegate.rebuild_statistics()

    def close(self) -> None:
        try:
            self.delegate.close()
        finally:
            self.cache.close()
