"""去重缓存 — 对齐 TECHNICAL_DESIGN.md §3.3。

dedupe_key = sha256(source|category|sub_category|stable_id)
stable_id 按类别：news/web 取 url；chain 取 tx_hash/symbol；macro/finance 取 sub_category+date。
"""
from __future__ import annotations

import hashlib

from data_center.core.contract import DataRecord


def stable_id(rec: DataRecord) -> str:
    """类别感知的稳定标识，用于跨运行去重。"""
    if rec.category in ("news", "web"):
        url = (
            rec.metrics.get("url")
            or rec.metrics.get("link")
            or (rec.events[0].get("url") if rec.events else "")
        )
        return url or rec.sub_category
    if rec.category == "chain":
        tx = rec.metrics.get("tx_hash")
        if tx:
            return tx  # 链上交易按 tx_hash 唯一去重
        # 行情/TVL/Gas 类（ccxt/defillama/etherscan）：持续采集场景下 symbol 固定，
        # 加入时间桶（分钟级）让不同次采集保留新行，避免旧值被永久锁定。
        sym = rec.metrics.get("symbol", rec.sub_category)
        ts_bucket = (rec.timestamp or "")[:16]  # YYYY-MM-DDTHH:MM
        return f"{sym}|{ts_bucket}"
    # macro / finance
    return f"{rec.sub_category}:{rec.metrics.get('date', '')}"


def dedupe_key(rec: DataRecord) -> str:
    base = f"{rec.source}|{rec.category}|{rec.sub_category}|{stable_id(rec)}"
    return hashlib.sha256(base.encode()).hexdigest()


def dedupe(records: list[DataRecord]) -> list[DataRecord]:
    """按 dedupe_key 去重，保留首次出现的记录。"""
    seen: set[str] = set()
    out: list[DataRecord] = []
    for r in records:
        k = dedupe_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out
