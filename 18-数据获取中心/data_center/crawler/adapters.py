"""Crawler adapters — 提取字段 dict → DataRecord(category=web)。

把 Spider/Playwright 提取的字段 dict 转成统一 DataRecord 契约。
metrics 仅存扁平 string/number；summary/content 等长文本放 events；原始数据全量放 raw。
"""
from __future__ import annotations

from datetime import datetime, timezone

from data_center.core.contract import DataRecord, validate_record

# summary/content 类字段不进 metrics（长文本），放入 events
_EVENT_FIELDS = {"summary", "content", "description", "abstract"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def adapt_item(fields: dict, site: dict) -> DataRecord:
    """单条提取结果 → DataRecord。

    Args:
        fields: Spider/Playwright 提取的字段 dict（title/link/date/summary...）
        site: 站点配置（source/sub_category）
    """
    source = site.get("source", "crawler")
    sub_category = site.get("sub_category", "page")
    ts = _now_iso()

    metrics: dict = {}
    events: list[dict] = []
    for k, v in fields.items():
        if k in _EVENT_FIELDS:
            events.append({k: v})
        elif isinstance(v, (dict, list)):
            # 嵌套对象不进 metrics，保留在 raw
            continue
        elif isinstance(v, (int, float, str, bool)):
            metrics[k] = v
        # None 静默跳过

    rec = DataRecord(
        source=source,
        category="web",
        sub_category=sub_category,
        timestamp=ts,
        metrics=metrics,
        events=events,
        timeseries=[],
        raw=dict(fields),
    )
    validate_record(rec)
    return rec


def adapt_items(items: list[dict], site: dict) -> list[DataRecord]:
    """多条提取结果 → list[DataRecord]。"""
    return [adapt_item(item, site) for item in items]
