"""基本面快照 · Web3 子模块（币安 Web3 榜单 / 单币画像）。

读 18-数据获取中心 的 binance_web3_* 记录：
  - 优先 PostgreSQL（18 默认后端 DATA_CENTER_BACKEND=postgres）
  - 回退本地 SQLite（data_center.db）
  - 均只读，且 FAIL-OPEN（后端不可用 → data_quality=empty）

为什么要独立成模块：
  - 该数据是「榜单快照」结构，不适合塞进 19-DAL 的 mm_metrics 数值表；
  - 独立文件与主快照脚本解耦，便于单独演进与测试。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

_SOURCES = ("binance_web3_market", "binance_web3_token")


def _data_center_db_path() -> str:
    """18 数据采集中心 SQLite 路径（可被 DATA_CENTER_DB 覆盖）。"""
    env = os.environ.get("DATA_CENTER_DB")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "18-数据获取中心", "data_center.db"))


def _web3_sql() -> str:
    """取每个 sub_category 的最新一条（PG / SQLite 通用）。"""
    return """
        SELECT sub_category, timestamp, metrics, raw FROM (
            SELECT sub_category, timestamp, metrics, raw,
                   ROW_NUMBER() OVER (
                       PARTITION BY sub_category ORDER BY id DESC
                   ) AS rn
            FROM records
            WHERE source IN ('binance_web3_market', 'binance_web3_token')
        ) t WHERE rn = 1
    """


def _json_col(v):
    """兼容 PG jsonb（已是 dict）与 SQLite TEXT。"""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _load_from_pg() -> list[dict]:
    try:
        import psycopg2
    except Exception:
        return []

    try:
        conn = psycopg2.connect(
            host=os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
            port=int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
            user=os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
            password=os.environ.get("DATA_CENTER_PG_PASSWORD", ""),
            dbname=os.environ.get("DATA_CENTER_PG_DB", "data_center"),
            connect_timeout=3,
        )
        try:
            cur = conn.cursor()
            cur.execute(_web3_sql())
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return []

    return [
        {
            "sub_category": r[0],
            "timestamp": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
            "metrics": _json_col(r[2]),
            "raw": _json_col(r[3]),
        }
        for r in rows
    ]


def _load_from_sqlite() -> list[dict]:
    import sqlite3

    path = _data_center_db_path()
    if not os.path.isfile(path):
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = conn.execute(_web3_sql()).fetchall()
        finally:
            conn.close()
    except Exception:
        return []

    return [
        {
            "sub_category": r[0],
            "timestamp": r[1],
            "metrics": _json_col(r[2]),
            "raw": _json_col(r[3]),
        }
        for r in rows
    ]


def load_web3_records(window_h: int = 48) -> list[dict]:
    """读取 binance_web3_* 最新快照，按时间窗口过滤。"""
    records = _load_from_pg() or _load_from_sqlite()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_h)
    out: list[dict] = []
    for rec in records:
        try:
            rec_ts = datetime.fromisoformat(str(rec["timestamp"]).replace("Z", "+00:00"))
            if rec_ts.tzinfo is None:
                rec_ts = rec_ts.replace(tzinfo=timezone.utc)
            if rec_ts < cutoff:
                continue
        except Exception:
            continue
        if not rec["sub_category"] or not isinstance(rec["metrics"], dict):
            continue
        out.append(rec)
    return out


def _num(d: dict, key: str):
    v = d.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _items(records: list[dict], prefix: str, sort_key: str, limit: int) -> list[dict]:
    """按前缀筛出记录，按 sort_key 降序取 top N。"""
    items = []
    for rec in records:
        if not rec["sub_category"].startswith(prefix):
            continue
        m = rec["metrics"]
        raw = rec["raw"]
        items.append(
            {
                "symbol": m.get("symbol") or raw.get("symbol") or rec["sub_category"],
                "name": raw.get("name") or raw.get("name_cn"),
                "address": raw.get("contractAddress"),
                "chain": raw.get("chainId"),
                "ts": rec["timestamp"],
                "metrics": m,
                "raw": raw,
                "sort": _num(m, sort_key),
            }
        )
    items.sort(key=lambda x: (x["sort"] is not None, x["sort"] or 0), reverse=True)
    return items[:limit]


def _fmt_smart(x: dict) -> dict:
    m = x["metrics"]
    return {
        "symbol": x["symbol"],
        "inflow_usd": _num(m, "inflow_usd"),
        "traders": _num(m, "smart_traders"),
        "price_change_pct": _num(m, "price_change_pct"),
        "market_cap": _num(m, "market_cap"),
        "holders": _num(m, "holders"),
        "risk_level": _num(m, "risk_level"),
    }


def _fmt_social(x: dict) -> dict:
    m = x["metrics"]
    return {
        "symbol": x["symbol"],
        "hype": _num(m, "social_hype"),
        "sentiment_score": _num(m, "sentiment_score"),
        "sentiment": x["raw"].get("sentiment"),
        "summary": x["raw"].get("social_summary_cn"),
        "market_cap": _num(m, "market_cap"),
        "price_change_pct": _num(m, "price_change_24h"),
    }


def _fmt_holding(x: dict) -> dict:
    m = x["metrics"]
    return {
        "symbol": x["symbol"],
        "price": _num(m, "price"),
        "market_cap": _num(m, "market_cap"),
        "volume_24h": _num(m, "volume_24h"),
        "holders": _num(m, "holders"),
        "top10_pct": _num(m, "top10_holders_pct"),
        "dev_pct": _num(m, "dev_holding_pct"),
        "sniper_pct": _num(m, "sniper_holding_pct"),
        "insider_pct": _num(m, "insider_holding_pct"),
        "bundler_pct": _num(m, "bundler_holding_pct"),
        "smart_money_pct": _num(m, "smart_money_pct"),
        "kol_pct": _num(m, "kol_pct"),
        "kyc_holders": _num(m, "kyc_holders"),
        "risk_level": _num(m, "risk_level"),
    }


def _fmt_meme(x: dict) -> dict:
    m = x["metrics"]
    return {
        "symbol": x["symbol"],
        "score": _num(m, "score"),
        "rank": _num(m, "rank"),
        "market_cap": _num(m, "market_cap"),
        "liquidity": _num(m, "liquidity"),
        "holders": _num(m, "holders"),
        "top10_pct": _num(m, "top10_holders_pct"),
        "volume_bn_7d": _num(m, "volume_bn_7d"),
        "impression": _num(m, "impression"),
    }


def _fmt_narrative(x: dict) -> dict:
    m = x["metrics"]
    toks = x["raw"].get("tokens") or []
    return {
        "topic": m.get("topic_name") or x["raw"].get("name_cn"),
        "net_inflow_usd": _num(m, "net_inflow_usd"),
        "net_inflow_1h_usd": _num(m, "net_inflow_1h_usd"),
        "net_inflow_ath_usd": _num(m, "net_inflow_ath_usd"),
        "token_size": _num(m, "token_size"),
        "top_tokens": [
            {"symbol": t.get("symbol"), "net_inflow": t.get("netInflow")}
            for t in toks[:5]
            if isinstance(t, dict)
        ],
    }


def _fmt_profile(x: dict) -> dict:
    m = x["metrics"]
    return {
        "symbol": x["symbol"],
        "price": _num(m, "price"),
        "market_cap": _num(m, "market_cap"),
        "fdv": _num(m, "fdv"),
        "circulating_supply": _num(m, "circulating_supply"),
        "holders": _num(m, "holders"),
        "top10_pct": _num(m, "top10_holders_pct"),
        "kol_holders": _num(m, "kol_holders"),
        "pro_holders": _num(m, "pro_holders"),
        "smart_money_holders": _num(m, "smart_money_holders"),
    }


def _fmt_audit(x: dict) -> dict:
    m = x["metrics"]
    return {
        "symbol": x["symbol"],
        "risk_level": _num(m, "risk_level"),
        "risk_enum": x["raw"].get("riskLevelEnum"),
        "buy_tax": _num(m, "buy_tax"),
        "sell_tax": _num(m, "sell_tax"),
        "risk_hits": _num(m, "risk_hits"),
        "caution_hits": _num(m, "caution_hits"),
        "supported": _num(m, "is_supported"),
    }


def build_web3(ts: str) -> dict:
    """构造快照中的 web3 模块（结构对齐其它模块：timestamp/metrics/meta）。"""
    records = load_web3_records()
    has_data = bool(records)

    smart = [_fmt_smart(x) for x in _items(records, "web3_smart_money_", "inflow_usd", 15)]
    social = [_fmt_social(x) for x in _items(records, "web3_social_hype_", "social_hype", 15)]
    alpha = [_fmt_holding(x) for x in _items(records, "web3_alpha_", "holders", 15)]
    trending = [_fmt_holding(x) for x in _items(records, "web3_trending_", "volume_24h", 15)]
    meme = [_fmt_meme(x) for x in _items(records, "web3_meme_rank_", "score", 10)]
    narrative = [
        _fmt_narrative(x) for x in _items(records, "web3_narrative_", "net_inflow_usd", 10)
    ]
    profile = [_fmt_profile(x) for x in _items(records, "web3_token_profile_", "holders", 10)]
    audit = [_fmt_audit(x) for x in _items(records, "web3_token_audit_", "risk_level", 10)]

    total_inflow = sum(v["inflow_usd"] for v in smart if v["inflow_usd"] is not None)
    total_traders = sum(v["traders"] for v in smart if v["traders"] is not None)
    sentiments = [v["sentiment_score"] for v in social if v["sentiment_score"] is not None]
    total_narrative = sum(v["net_inflow_usd"] for v in narrative if v["net_inflow_usd"] is not None)
    risk_high = sum(1 for v in audit if (v["risk_level"] or 0) >= 4)
    risk_hits = sum(v["risk_hits"] for v in audit if v["risk_hits"] is not None)

    core = {
        "smart_money_top_inflow_usd": smart[0]["inflow_usd"] if smart else None,
        "smart_money_total_inflow_usd": total_inflow if smart else None,
        "smart_money_traders": total_traders if smart else None,
        "social_hype_top": social[0]["hype"] if social else None,
        "social_sentiment_avg": (
            round(sum(sentiments) / len(sentiments), 3) if sentiments else None
        ),
        "meme_top_score": meme[0]["score"] if meme else None,
        "narrative_total_inflow_usd": total_narrative if narrative else None,
        "alpha_count": len(alpha) or None,
        "high_risk_token_count": risk_high if audit else None,
        "risk_hit_total": risk_hits if audit else None,
    }
    core = {k: v for k, v in core.items() if v is not None}

    return {
        "timestamp": ts,
        "data": {
            "smart_money_stage": {"value": "24h 净流入", "label": "聪明钱口径"},
            "source_note": {"value": "binance_web3", "label": "币安 Web3 公开榜单"},
        },
        "metrics": {
            "core": core,
            "breakdown": {
                "smart_money_inflow_top": smart,
                "social_hype_top": social,
                "alpha_holding_top": alpha,
                "trending_volume_top": trending,
                "meme_score_top": meme,
                "narrative_top": narrative,
                "token_profile_top": profile,
                "token_audit_top": audit,
                "record_count": len(records),
            },
        },
        "meta": {
            "last_update": ts,
            "source": ["18-data_center.records"] if has_data else [],
            "data_quality": "good" if has_data else "empty",
        },
    }
