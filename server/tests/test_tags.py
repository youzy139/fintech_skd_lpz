from __future__ import annotations

from market_core.domain.tags import record_tags


def test_topic_keywords_use_boundaries_and_case_insensitive_matching():
    tags = record_tags("AI and semiconductors", {"text": "DRAM demand rises as the Fed discusses a rate cut"})
    assert "人工智能" in tags
    assert "半导体" in tags
    assert "利率与货币政策" in tags
    assert "人工智能" not in record_tags("said and detail", {"text": "ordinary text"})


def test_structural_tags_only_use_known_fields():
    tags = record_tags("研究", {"_sheet": "X01", "institution": "机构A", "相关方": "某机构", "HomeCountry": 1, "close": 100, "yield": 2.5})
    assert {"Sheet X01", "机构:机构A", "相关方:某机构", "国家编码:1", "收盘价", "收益率"} <= tags
    assert record_tags("无匹配", {"text": "普通文本"}) == set()
