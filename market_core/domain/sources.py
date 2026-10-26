from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class SourceFile:
    id: str
    kind: str
    path: str
    absolute_path: Path
    size: int
    mtime_ns: int

    @staticmethod
    def create(root: Path, path: Path, kind: str) -> SourceFile:
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        return SourceFile(hashlib.sha1(relative.encode()).hexdigest()[:16], kind, relative, path, stat.st_size, stat.st_mtime_ns)


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    record_index: int
    event_date: str | None
    title: str
    payload: dict[str, Any]


@dataclass
class ImportResult:
    source_id: str
    status: str
    record_count: int = 0
    error_count: int = 0
    sheets: list[str] = field(default_factory=list)
    error: str | None = None


RecordIterator = Iterator[SourceRecord]
