from __future__ import annotations

import csv
from pathlib import Path

import pytest
from redis.exceptions import RedisError

from app.core.resilience import CircuitBreaker
from app.services.cache import CachedCatalogStore, LocalJsonCache, RedisJsonCache
from app.services.catalog import CatalogStore
from market_core.domain.sources import SourceFile


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.available = True
        self.closed = False
        self.calls = 0

    def get(self, key):
        self.calls += 1
        if not self.available:
            raise RedisError("offline")
        return self.values.get(key)

    def set(self, key, value, ex):
        self.calls += 1
        if not self.available:
            raise RedisError("offline")
        self.values[key] = value

    def close(self):
        self.closed = True


def make_source(tmp_path: Path, rows: list[tuple[str, str]]) -> SourceFile:
    path = tmp_path / "科技.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at_twitter", "text"])
        writer.writeheader()
        for day, text in rows:
            writer.writerow({"created_at_twitter": day, "text": text})
    return SourceFile.create(tmp_path, path, "social")


def populated_store(tmp_path: Path) -> tuple[CatalogStore, FakeRedis, CachedCatalogStore]:
    store = CatalogStore(tmp_path / "catalog.db")
    store.import_file(make_source(tmp_path, [("2024-01-01", "AI"), ("2024-01-02", "半导体")]))
    client = FakeRedis()
    cached = CachedCatalogStore(store, RedisJsonCache(client, "test:catalog", 60), LocalJsonCache(128, 15))
    return store, client, cached


def test_cache_hits_and_content_version_invalidation(tmp_path: Path):
    store, client, cached = populated_store(tmp_path)
    try:
        first = cached.summary()
        assert cached.summary() == first
        assert cached.cache_stats["local"]["hits"] == 1
        assert cached.cache_stats["hits"] == 0
        assert cached.cache_stats["writes"] == 1
        old_version = cached.data_version()
        cached.import_file(make_source(tmp_path, [("2024-01-01", "AI"), ("2024-01-02", "半导体"), ("2024-01-03", "通胀")]))
        assert cached.data_version() != old_version
        assert cached.summary()["total_records"] == 3
        assert cached.cache_stats["local"]["hits"] == 1
        records = cached.list_records(None, None, None, 0, 20, "social")
        assert cached.list_records(None, None, None, 0, 20, "social") == records
        assert cached.cache_stats["local"]["hits"] == 2
    finally:
        cached.close()


def test_redis_is_shared_second_layer_and_local_values_are_isolated(tmp_path: Path):
    store, client, first = populated_store(tmp_path)
    second = CachedCatalogStore(store, RedisJsonCache(client, "test:catalog", 60), LocalJsonCache(128, 15))
    try:
        result = first.summary()
        result["total_records"] = -1
        assert first.summary()["total_records"] == 2
        assert second.summary()["total_records"] == 2
        assert second.cache_stats["local"]["hits"] == 0
        assert second.cache_stats["hits"] == 1
        assert second.summary()["total_records"] == 2
        assert second.cache_stats["local"]["hits"] == 1
    finally:
        first.close()
        second.close()


def test_local_cache_is_bounded_and_expires():
    now = [0.0]
    cache = LocalJsonCache(2, 10, clock=lambda: now[0])
    cache.set("a", {"value": 1}); cache.set("b", {"value": 2}); cache.set("c", {"value": 3})
    assert cache.get("a") == (False, None)
    assert cache.snapshot()["evictions"] == 1
    assert cache.get("b")[0]
    now[0] = 11
    assert cache.get("b") == (False, None)
    assert cache.snapshot()["expirations"] == 1
    with pytest.raises(ValueError):
        LocalJsonCache(0, 10)


def test_redis_failure_falls_back_without_changing_results(tmp_path: Path):
    store, client, cached = populated_store(tmp_path)
    try:
        expected = store.summary()
        assert cached.summary() == expected
        client.available = False
        assert cached.summary() == expected
        assert cached.overview("social")["records"] == 2
        assert cached.list_tags("social")
        assert cached.cache_stats["errors"] >= 2
        client.available = True
        assert cached.summary() == expected
    finally:
        cached.close()
    assert client.closed


def test_large_offsets_bypass_cache_and_ttl_is_validated(tmp_path: Path):
    store, client, cached = populated_store(tmp_path)
    try:
        result = cached.list_records(None, None, None, 20, 20)
        assert result["offset"] == 20
        assert client.values == {}
        with pytest.raises(ValueError, match="TTL"):
            RedisJsonCache(client, "test", 0)
    finally:
        cached.close()


def test_circuit_prevents_repeated_dns_and_recovers_after_cooldown(tmp_path):
    store, client, cached = populated_store(tmp_path)
    now = [0.0]
    cached.cache.breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=5, clock=lambda: now[0])
    try:
        expected = store.summary()
        client.available = False
        assert cached.summary() == expected
        assert cached.overview("social")["records"] == 2
        assert cached.cache_stats["circuit"]["state"] == "open"
        calls = client.calls
        assert cached.list_tags("social")
        assert cached.list_tags("social")
        assert client.calls == calls
        assert cached.cache_stats["circuit"]["short_circuits"] >= 2
        now[0] = 6
        client.available = True
        assert cached.list_files("social", None, 0, 20)["total"] == 1
        assert cached.cache_stats["circuit"]["state"] == "closed"
        assert client.calls == calls + 2
    finally:
        cached.close()
