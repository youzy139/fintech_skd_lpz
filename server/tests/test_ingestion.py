from __future__ import annotations

import csv
from pathlib import Path

import pytest

from market_core.ingestion.assets import AssetRepository


def make_dataset(tmp_path: Path) -> Path:
    root = tmp_path / "目标资产价格变量"
    root.mkdir()
    with (root / "代码对照.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["大类", "名称", "Wind代码", "字段", "交易日历", "起始", "结束", "条数", "状态", "备注"])
        writer.writerow(["权益", "测试指数", "TEST", "close", "测试", "2024-01-01", "2024-01-04", 4, "ok", ""])
        writer.writerow(["债券", "缺失债券", "MISSING", "yield", "测试", "2024-01-01", "2024-01-04", 4, "missing", ""])
    with (root / "测试指数.csv").open("w", encoding="utf-8", newline="") as handle:
        handle.write("date,close\n2024-01-02,100\n2024-01-02,101\n2024-01-03,bad\n2024-01-04,103\n")
    return root.parent


def test_load_all_deduplicates_and_reports_quality(tmp_path: Path):
    repository = AssetRepository(make_dataset(tmp_path))
    series, quality = repository.load_all()
    assert len(series) == 1
    assert list(series[0].frame["value"]) == [101.0, 103.0]
    assert quality.catalog_records == 2
    assert quality.loaded_assets == 1
    assert quality.duplicate_dates == 1
    assert quality.invalid_rows == 1


def test_field_mismatch_is_not_silently_accepted(tmp_path: Path):
    data_root = make_dataset(tmp_path)
    path = data_root / "目标资产价格变量" / "测试指数.csv"
    path.write_text("date,yield\n2024-01-02,2.5\n", encoding="utf-8")
    repository = AssetRepository(data_root)
    with pytest.raises(ValueError, match="字段"):
        repository.load(repository.catalog()[0])
