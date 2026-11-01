from __future__ import annotations

from typing import Any

from app.core.config import AppConfig
from app.services.catalog_factory import create_catalog
from app.services.contracts import CatalogReader


class DataCatalogService:
    def __init__(self, config: AppConfig, catalog: CatalogReader | None = None):
        self.storage_mode = config.storage_mode
        self.catalog = catalog or create_catalog(config)

    def data_version(self) -> str:
        return self.catalog.data_version()

    def source_summary(self) -> dict[str, Any]:
        return self.catalog.summary()

    def source_overview(self, kind: str | None) -> dict[str, Any]:
        return self.catalog.overview(kind)

    def source_tags(self, kind: str | None) -> list[dict[str, Any]]:
        return self.catalog.list_tags(kind)

    def source_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        return self.catalog.list_files(kind, query, offset, limit)

    def source_records(self, source_id: str | None, query: str | None, date: str | None, offset: int, limit: int, kind: str | None = None, tag: str | None = None, tags: list[str] | None = None, match: str = "any") -> dict[str, Any]:
        return self.catalog.list_records(source_id, query, date, offset, limit, kind, tag, tags, match)

    def close(self) -> None:
        close = getattr(self.catalog, "close", None)
        if close:
            close()
