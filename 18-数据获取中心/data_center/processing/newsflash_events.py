"""newsflash × K线 对齐回填路径 — SPEC-D1 §2.4 回填路径 2（公告/快讯对齐）。

口径（预注册，禁止事后调整）：
  - 上游 od_event_type → D1 Top5 直映；未命中桶按描述关键词补识别
  - 去重键 = (d1_event_type, UTC 日, asset_scope)：同日同类只留最早一条
  - source="announcement"，attribution="strong"（快讯=直接事件流；
    仅 kline_detected 为 weak）
  - ts_precision="second"；reaction 用日 K 对齐，只算 T+24h/T+7d
  - market_state 留空（funding/OI 覆盖不足，按 D4 降级方案后续补 regime）

FAIL-OPEN：单条异常跳过，不阻塞批量。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from data_center.processing.event_reaction import compute_reaction

logger = logging.getLogger("data_center.processing.newsflash_events")

# ── 上游 od_event_type → D1 事件类型直映 ────────────────────
_EVENT_TYPE_MAP = {
    "monetary_policy": "macro.rate",
    "security_incident": "hack.security",
    "crypto_regulation": "regulation.crypto",
    "us_policy": "regulation.crypto",
}

# ── 描述关键词补识别（优先级高于直映，从上到下首个命中）─────
_KEYWORD_RULES = [
    ("etf.regulation", ["ETF"]),
    ("unlock.supply", ["解锁", "unlock"]),
    ("listing.exchange", ["将上线", "上线", "首发上线", "listing"]),
]

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _TAG_RE.sub("", s)


def classify_newsflash(rec: Any) -> str:
    """返回 D1 事件类型；未命中返回 ""（不入库）。"""
    if not isinstance(rec, dict):
        return ""
    desc = _strip_html(str(rec.get("description") or ""))
    for etype, kws in _KEYWORD_RULES:
        if any(kw in desc for kw in kws):
            return etype
    return _EVENT_TYPE_MAP.get(str(rec.get("od_event_type") or rec.get("event_type") or ""), "")


def _parse_ts(rec: dict) -> int:
    """published_ms（毫秒字符串）→ epoch 秒；缺失回退 _fallback_ts（ISO）。失败返回 0。"""
    try:
        ms = int(str(rec.get("published_ms") or rec.get("publishTimestamp") or "0"))
        if ms > 0:
            return ms // 1000
    except (TypeError, ValueError):
        pass
    try:
        iso = str(rec.get("_fallback_ts") or "")
        if iso:
            return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        pass
    return 0


def _day_bucket(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def build_events_from_newsflash(recs: Any, prices: Any, store: Any) -> dict:
    """快讯批量 → 事件库。返回统计 {stored, deduped, skipped_unmapped, skipped_bad}。

    FAIL-OPEN：整体/单条异常不抛。
    """
    stats = {"stored": 0, "deduped": 0, "skipped_unmapped": 0, "skipped_bad": 0}
    try:
        if not isinstance(recs, (list, tuple)):
            return stats
        seen: set[tuple] = set()
        for rec in recs:
            try:
                if not isinstance(rec, dict):
                    stats["skipped_bad"] += 1
                    continue
                etype = classify_newsflash(rec)
                if not etype:
                    stats["skipped_unmapped"] += 1
                    continue
                ts = _parse_ts(rec)
                if ts <= 0:
                    stats["skipped_bad"] += 1
                    continue
                key = (etype, _day_bucket(ts))
                if key in seen:
                    stats["deduped"] += 1
                    continue
                seen.add(key)
                ev = {
                    "event_id": f"EV-newsflash-{key[1]}-{etype}",
                    "event_type": etype,
                    "asset_scope": ["BTC"],  # 降级：日 K 基准统一 BTC
                    "trigger_ts": ts,
                    "ts_onchain_visible": None,
                    "unlock_pct_supply": None,
                    "ts_precision": "second",
                    "market_state": {},
                    "reaction": compute_reaction(prices, ts),
                    "source": "announcement",
                    "attribution": "strong",
                }
                if store.add(ev):
                    stats["stored"] += 1
                else:
                    stats["skipped_bad"] += 1
            except Exception as e:  # noqa: BLE003  单条 FAIL-OPEN
                logger.warning(
                    "[FAIL-OPEN] newsflash 单条异常 %s: %s", type(e).__name__, str(e)[:200]
                )
                stats["skipped_bad"] += 1
        return stats
    except Exception as e:  # noqa: BLE003
        logger.warning(
            "[FAIL-OPEN] build_events_from_newsflash 异常 %s: %s", type(e).__name__, str(e)[:200]
        )
        return stats
