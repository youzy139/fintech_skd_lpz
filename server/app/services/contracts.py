from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from market_core.domain.sources import SourceFile


@runtime_checkable
class CatalogReader(Protocol):
    def data_version(self) -> str: ...

    def summary(self) -> dict[str, Any]: ...

    def overview(self, kind: str | None) -> dict[str, Any]: ...

    def list_tags(self, kind: str | None) -> list[dict[str, Any]]: ...

    def list_files(self, kind: str | None, query: str | None, offset: int, limit: int) -> dict[str, Any]: ...

    def list_records(
        self,
        source_id: str | None,
        query: str | None,
        date: str | None,
        offset: int,
        limit: int,
        kind: str | None = None,
        tag: str | None = None,
        tags: list[str] | None = None,
        match: str = "any",
    ) -> dict[str, Any]: ...


@runtime_checkable
class CatalogWriter(Protocol):
    def is_unchanged(self, source: SourceFile) -> bool: ...

    def import_file(self, source: SourceFile, batch_size: int = 1000) -> dict[str, Any]: ...

    def rebuild_statistics(self) -> dict[str, int]: ...


@runtime_checkable
class CatalogStorage(CatalogReader, CatalogWriter, Protocol):
    def close(self) -> None: ...


@runtime_checkable
class SnapshotStorage(Protocol):
    def save(self, key: str, value: object) -> None: ...

    def close(self) -> None: ...
