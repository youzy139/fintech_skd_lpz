from __future__ import annotations

import re
from typing import Any


TOPIC_KEYWORDS = {
    "通胀": ("通胀", "inflation", "cpi"),
    "利率与货币政策": ("利率", "加息", "降息", "货币政策", "interest rate", "federal reserve", "fed", "rate cut", "rate hike"),
    "宏观经济": ("宏观经济", "gdp", "pmi", "非农", "就业", "economic growth", "recession"),
    "股票市场": ("股票", "股市", "equity", "equities", "stock market", "s&p", "nasdaq"),
    "债券与收益率": ("债券", "国债", "收益率", "bond", "bonds", "treasury", "yield"),
    "外汇": ("外汇", "汇率", "美元", "欧元", "日元", "forex", "dollar", "euro", "yen"),
    "商品与能源": ("商品", "原油", "黄金", "白银", "铜", "oil", "gold", "silver", "copper", "commodity"),
    "人工智能": ("人工智能", "ai", "artificial intelligence", "openai", "anthropic", "claude", "chatgpt"),
    "半导体": ("半导体", "芯片", "semiconductor", "dram", "nand", "nvidia", "英伟达"),
    "财报与业绩": ("财报", "业绩", "利润", "营收", "earnings", "profit", "revenue"),
    "政策与监管": ("政策", "监管", "关税", "policy", "regulation", "regulator", "tariff"),
    "地缘政治": ("地缘", "战争", "冲突", "制裁", "geopolitical", "war", "sanction", "sanctions"),
}


def _pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword.casefold())
    if keyword.isascii():
        return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")
    return re.compile(escaped)


TOPIC_RULES = {tag: tuple(_pattern(keyword) for keyword in keywords) for tag, keywords in TOPIC_KEYWORDS.items()}


def record_tags(title: str, payload: dict[str, Any]) -> set[str]:
    values = [title, *(value for value in payload.values() if isinstance(value, (str, int, float)))]
    text = " ".join(str(value) for value in values).casefold()
    tags = {tag for tag, patterns in TOPIC_RULES.items() if any(pattern.search(text) for pattern in patterns)}
    structural_fields = (("_sheet", "Sheet "), ("institution", "机构:"), ("相关方", "相关方:"), ("HomeCountry", "国家编码:"))
    for field, prefix in structural_fields:
        value = payload.get(field)
        if value is not None and str(value).strip():
            tags.add(f"{prefix}{value}")
    if "close" in payload:
        tags.add("收盘价")
    if "yield" in payload:
        tags.add("收益率")
    return tags
