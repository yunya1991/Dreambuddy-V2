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

# ── P0-2 快讯 → 因子映射（SPEC §2.10 / §2.9.2）───────────────
# 两套独立映射用于 sens_f 稳定性检验；任何改动必须升 MAPPING_VERSION。
MAPPING_VERSION = "news-factor-v1"

# 映射 A：od_event_type 直映维度（粗粒度、覆盖优先）
EVENT_TYPE_FACTOR_DIMS = {
    "market_sentiment": ("D4",),
    "monetary_policy": ("D1",),
    "crypto_regulation": ("D1", "D4"),
    "us_policy": ("D1",),
    "security_incident": ("C7", "D4"),
    "token_milestone": ("C7", "D3"),
    "project_ecosystem": ("C7", "D3"),
    "geopolitics": ("D1",),
    "us_data": ("D1",),
}

# 映射 B：关键词优先（独立构造、粒度更细）；未命中回落到 B 自己的粗表
KEYWORD_FACTOR_RULES = (
    (("ETF", "etf"), ("D2",)),
    (("减半", "halving", "销毁", "burn"), ("C7",)),
    (("解锁", "unlock"), ("C7",)),
    (("上线", "listing", "首发"), ("D4", "D3")),
    (("加息", "降息", "利率", "rate hike", "rate cut"), ("D1",)),
    (("黑客", "被盗", "漏洞", "hack", "exploit"), ("C7",)),
    (("监管", "SEC", "诉讼", "lawsuit", "regulation"), ("D1", "D4")),
    (("巨鲸", "whale", "持仓", "增持", "减持"), ("D2",)),
)
_EVENT_TYPE_FACTOR_DIMS_V2 = {
    "market_sentiment": ("D4",),
    "monetary_policy": ("D1",),
    "crypto_regulation": ("D4",),
    "us_policy": ("D1",),
    "security_incident": ("C7",),
    "token_milestone": ("C7",),
    "project_ecosystem": ("D3",),
    "geopolitics": ("D1",),
    "us_data": ("D1",),
}

_FACTORS_BY_DIM: dict[str, tuple[str, ...]] = {}


def _factors_by_dim() -> dict[str, tuple[str, ...]]:
    """维度 → 因子 ID（延迟构建，避免模块加载时循环依赖）。"""
    if not _FACTORS_BY_DIM:
        from data_center.processing.dimension_context import DIMENSION_MAP
        from data_center.processing.factor_series_map import SERIES_MAP

        acc: dict[str, list[str]] = {}
        for fid, meta in SERIES_MAP.items():
            if meta.get("source") == "none":  # 无序列的因子不参与映射
                continue
            dim = DIMENSION_MAP.get(fid.split(".")[0])
            if dim:
                acc.setdefault(dim, []).append(fid)
        _FACTORS_BY_DIM.update({k: tuple(v) for k, v in acc.items()})
    return _FACTORS_BY_DIM


def map_event_to_dims(rec: Any, mapping: str = "v1") -> tuple[tuple[str, ...], str]:
    """快讯 → (维度元组, 命中来源)。FAIL-OPEN → ((), "none")。"""
    try:
        if not isinstance(rec, dict):
            return (), "none"
        if mapping == "v2":
            text = _strip_html(f"{rec.get('title') or ''} {rec.get('description') or ''}")
            for kws, dims in KEYWORD_FACTOR_RULES:
                if any(k in text for k in kws):
                    return tuple(dims), "keyword"
            et = str(rec.get("od_event_type") or "")
            return tuple(_EVENT_TYPE_FACTOR_DIMS_V2.get(et, ())), "event_type_v2"
        et = str(rec.get("od_event_type") or "")
        return tuple(EVENT_TYPE_FACTOR_DIMS.get(et, ())), "event_type"
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] map_event_to_dims %s: %s", type(e).__name__, str(e)[:120])
        return (), "none"


def map_event_to_factors(rec: Any, mapping: str = "v1") -> tuple[tuple[str, ...], str]:
    """快讯 → (因子 ID 元组, 命中来源)。"""
    dims, src = map_event_to_dims(rec, mapping)
    by_dim = _factors_by_dim()
    out: list[str] = []
    for d in dims:
        out.extend(by_dim.get(d, ()))
    return tuple(dict.fromkeys(out)), src


def mapping_coverage(recs: Any, mapping: str = "v1") -> dict:
    """映射覆盖率：mapped / total，附按来源与事件类型分布。"""
    stats: dict[str, Any] = {
        "mapping_version": MAPPING_VERSION,
        "mapping": mapping,
        "total": 0,
        "mapped": 0,
        "coverage": 0.0,
        "by_source": {},
        "by_event_type": {},
        "unmapped_types": {},
    }
    try:
        if recs is None or isinstance(recs, (str, bytes, dict)):
            return stats
        for rec in recs:
            stats["total"] += 1
            dims, src = map_event_to_dims(rec, mapping)
            stats["by_source"][src] = stats["by_source"].get(src, 0) + 1
            et = str(rec.get("od_event_type") or "") if isinstance(rec, dict) else ""
            stats["by_event_type"][et] = stats["by_event_type"].get(et, 0) + 1
            if dims:
                stats["mapped"] += 1
            else:
                stats["unmapped_types"][et] = stats["unmapped_types"].get(et, 0) + 1
        stats["coverage"] = round(stats["mapped"] / stats["total"], 4) if stats["total"] else 0.0
        return stats
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] mapping_coverage %s: %s", type(e).__name__, str(e)[:120])
        return stats


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
