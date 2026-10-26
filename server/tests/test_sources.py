from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from market_core.domain.sources import SourceFile
from market_core.ingestion.sources import discover_sources, iter_records, source_sheets


def source(tmp_path: Path, name: str, kind: str) -> SourceFile:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    return SourceFile.create(tmp_path, path, kind)


def test_news_multiline_html_is_one_logical_record(tmp_path: Path):
    item = source(tmp_path, "news.csv", "news")
    with item.absolute_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["1", "标题", '<p>第一行\n第二行</p>', "来源", "0", "", "[]", "1", "2", "2024-01-02", "1"])
    records = list(iter_records(item))
    assert len(records) == 1
    assert records[0].event_date == "2024-01-02"
    assert "\n" in records[0].payload["column_3"]


def test_indicator_reads_every_sheet(tmp_path: Path):
    item = source(tmp_path, "indicators.xlsx", "indicator")
    workbook = Workbook()
    workbook.active.title = "X01"
    workbook["X01"].append(["日期", "序列1"])
    workbook["X01"].append(["2024-01-01", 2])
    workbook.create_sheet("X02").append(["日期", "序列1"])
    workbook["X02"].append(["2024-01-02", 3])
    workbook.save(item.absolute_path)
    records = list(iter_records(item))
    assert [record.payload["_sheet"] for record in records] == ["X01", "X02"]
    assert source_sheets(item) == ["X01", "X02"]


def test_research_metadata_is_parsed(tmp_path: Path):
    item = source(tmp_path, "2024-05-02-机构A-市场摘要.md", "research")
    item.absolute_path.write_text("### 主要观点\n正文", encoding="utf-8")
    record = list(iter_records(item))[0]
    assert record.event_date == "2024-05-02"
    assert record.title == "市场摘要"
    assert record.payload["institution"] == "机构A"
