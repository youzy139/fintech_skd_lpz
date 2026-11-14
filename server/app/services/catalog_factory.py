from __future__ import annotations

from app.core.config import AppConfig
from app.services.cache import CachedCatalogStore, RedisJsonCache, local_cache_from_environment
from app.services.catalog import CatalogStore
from app.services.clickhouse_store import ClickHouseCatalogStore
from app.services.contracts import CatalogReader, CatalogStorage
from app.services.remote_catalog import RemoteCatalogClient


def create_catalog(config: AppConfig) -> CatalogStorage:
    if config.storage_mode == "distributed":
        catalog: CatalogStorage = ClickHouseCatalogStore(config.clickhouse)
    else:
        catalog = CatalogStore(config.database_path)
    local = local_cache_from_environment(config.redis["ttl_seconds"])
    if config.redis.get("enabled", False):
        shared = RedisJsonCache.from_config(config.redis)
        return CachedCatalogStore(catalog, shared, local)
    if local is not None:
        return CachedCatalogStore(catalog, None, local, namespace=config.redis["namespace"])
    return catalog


def create_catalog_reader(config: AppConfig) -> CatalogReader:
    if config.data_service["url"]:
        return RemoteCatalogClient(config.data_service["url"], config.data_service["timeout_seconds"])
    return create_catalog(config)
