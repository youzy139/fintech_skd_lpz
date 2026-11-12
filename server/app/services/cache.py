from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable

import redis
from redis.exceptions import RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.resilience import CircuitBreaker
from app.services.contracts import CatalogStorage
from market_core.domain.sources import SourceFile


class LocalJsonCache:
    def __init__(self, max_entries: int = 128, ttl_seconds: int = 15, clock: Callable[[], float] = time.monotonic):
        if max_entries < 1 or ttl_seconds < 1:
            raise ValueError("本地缓存容量和 TTL 必须大于 0")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.values: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.lock = Lock()
        self.stats = {"hits": 0, "misses": 0, "writes": 0, "evictions": 0, "expirations": 0}

    def get(self, key: str) -> tuple[bool, Any]:
        now = self.clock()
        with self.lock:
            entry = self.values.pop(key, None)
            if entry is None:
                self.stats["misses"] += 1
                return False, None
            expires, value = entry
            if expires <= now:
                self.stats["misses"] += 1
                self.stats["expirations"] += 1
                return False, None
            self.values[key] = entry
            self.stats["hits"] += 1
            return True, copy.deepcopy(value)

    def set(self, key: str, value: Any) -> None:
        with self.lock:
            self.values.pop(key, None)
            self.values[key] = (self.clock() + self.ttl_seconds, copy.deepcopy(value))
            self.stats["writes"] += 1
            while len(self.values) > self.max_entries:
                self.values.popitem(last=False)
                self.stats["evictions"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {**self.stats, "entries": len(self.values), "max_entries": self.max_entries, "ttl_seconds": self.ttl_seconds}


class RedisJsonCache:
    def __init__(self, client: Any, namespace: str, ttl_seconds: int, breaker: CircuitBreaker | None = None):
        if ttl_seconds < 1:
            raise ValueError("缓存 TTL 必须大于 0 秒")
        self.client = client
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self.breaker = breaker or CircuitBreaker()
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
            retry=Retry(NoBackoff(), 0),
        )
        return cls(client, settings["namespace"], int(settings["ttl_seconds"]))

    def get(self, key: str) -> Any | None:
        if not self.breaker.before_call():
            self.stats["errors"] += 1
            return None
        try:
            value = self.client.get(key)
        except RedisError:
            self.breaker.after_call(False)
            self.stats["errors"] += 1
            return None
        self.breaker.after_call(True)
        try:
            if value is None:
                self.stats["misses"] += 1
                return None
            self.stats["hits"] += 1
            return json.loads(value)
        except (TypeError, ValueError):
            self.stats["errors"] += 1
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            self.stats["errors"] += 1
            return
        if not self.breaker.before_call():
            self.stats["errors"] += 1
            return
        try:
            self.client.set(key, serialized, ex=self.ttl_seconds)
            self.breaker.after_call(True)
            self.stats["writes"] += 1
        except RedisError:
            self.breaker.after_call(False)
            self.stats["errors"] += 1

    def close(self) -> None:
        self.client.close()


class CachedCatalogStore:
    def __init__(self, delegate: CatalogStorage, cache: RedisJsonCache, local: LocalJsonCache | None = None):
        self.delegate = delegate
        self.cache = cache
        self.local = local

    @property
    def cache_stats(self) -> dict[str, Any]:
        return {
            **self.cache.stats,
            "namespace": self.cache.namespace,
            "ttl_seconds": self.cache.ttl_seconds,
            "circuit": self.cache.breaker.snapshot(),
            "local": self.local.snapshot() if self.local else {"enabled": False},
            "shared": {"enabled": True, **self.cache.stats, "ttl_seconds": self.cache.ttl_seconds},
        }

    def data_version(self) -> str:
        return self.delegate.data_version()

    def _cached(self, method: str, arguments: Any, loader: Callable[[], Any]) -> Any:
        identity = json.dumps([self.cache.namespace, self.data_version(), method, arguments], ensure_ascii=False, sort_keys=True, default=str)
        key = self.cache.namespace + ":" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if self.local:
            hit, value = self.local.get(key)
            if hit:
                return value
        cached = self.cache.get(key)
        if cached is not None:
            if self.local:
                self.local.set(key, cached)
            return cached
        result = loader()
        self.cache.set(key, result)
        if self.local:
            self.local.set(key, result)
        return result

    def summary(self) -> dict[str, Any]:
        return self._cached("summary", None, self.delegate.summary)

    def overview(self, kind: str | None) -> dict[str, Any]:
        return self._cached("overview", kind, lambda: self.delegate.overview(kind))

    def governance(self, kind: str | None) -> dict[str, Any]:
        return self.delegate.governance(kind)

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


def local_cache_from_environment(redis_ttl_seconds: int) -> LocalJsonCache | None:
    if os.getenv("CATALOG_LOCAL_CACHE_ENABLED", "true").lower() != "true":
        return None
    entries = int(os.getenv("CATALOG_LOCAL_CACHE_ENTRIES", "128"))
    ttl = int(os.getenv("CATALOG_LOCAL_CACHE_TTL_SECONDS", str(min(15, redis_ttl_seconds))))
    return LocalJsonCache(entries, ttl)
