"""DataRecord 统一数据契约 — 对齐 TECHNICAL_DESIGN.md §3.1。

所有采集器（SDK 轨 + 爬虫轨）产出统一 DataRecord，便于跨子系统消费与去重缓存。
约束：metrics 仅存 number/string，不嵌套对象；raw 保留上游原始响应以便溯源。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from data_center.core.errors import ContractError

# 合法的 category 域
CATEGORIES = ("macro", "finance", "chain", "news", "web")


@dataclass
class DataRecord:
    source: str             # "fred"|"akshare"|"ccxt"|"etherscan"|"rsshub"|"scrapy"...
    category: str           # CATEGORIES 之一
    sub_category: str        # "cpi"|"ohlcv"|"whale"|"rss"...
    timestamp: str          # ISO8601 采集时间
    metrics: dict           # 扁平 number/string（core/breakdown）
    events: list[dict]      # 事件流（新闻/巨鲸/政策）
    timeseries: list[dict]  # 时序列（行情/指标）
    raw: dict                # 原始 payload（溯源）
    schema_version: str = "1.0"


def validate_record(rec: DataRecord) -> None:
    """校验 DataRecord 契约，违规抛 ContractError。"""
    if not rec.source or not rec.category or not rec.sub_category:
        raise ContractError("source/category/sub_category 不能为空")
    if rec.category not in CATEGORIES:
        raise ContractError(f"category {rec.category!r} 非法，应为 {CATEGORIES}")
    _validate_timestamp(rec.timestamp)
    _validate_metrics(rec.metrics)


def _validate_timestamp(ts: str) -> None:
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as e:
        raise ContractError(f"timestamp 非合法 ISO8601: {ts!r}") from e


def _validate_metrics(metrics: dict) -> None:
    for k, v in metrics.items():
        if isinstance(v, (dict, list)):
            raise ContractError(
                f"metrics[{k!r}] 禁止嵌套 {type(v).__name__}，仅允许 number/string"
            )
        if not isinstance(v, (int, float, str, bool)):
            raise ContractError(
                f"metrics[{k!r}] 类型 {type(v).__name__} 非法，仅允许 number/string"
            )
