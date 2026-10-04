"""三屏趋势系统 — 数据中心查询适配器

从 18-数据获取中心 的 SQLite 数据库读取多维基本面数据，
为数据驱动的三屏分析提供统一的数据查询接口。

数据源覆盖：
- 情绪面：恐惧贪婪指数 (fear_greed / fear_greed_enhanced)
- 资金流：BTC ETF 净流入 (etf_flow)
- 链上：稳定币市值变化 (stablecoin_transparency)、DeFi TVL (defillama)
- 衍生品：资金费率 (coinglass)、期权持仓 (deribit)
- 宏观：美联储利率/CPI/M2 (fred)

设计原则：
- FAIL-OPEN：任一数据源不可用时返回 None，不阻塞整体分析
- 统一接口：所有查询返回 dict，含 value/confidence/direction/source/timestamp
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# 数据中心数据库路径
_DC_DB_PATH = os.environ.get(
    "DATA_CENTER_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "18-数据获取中心" / "data_center.db"),
)


def _get_conn() -> Optional[sqlite3.Connection]:
    """获取数据库连接（失败返回 None）"""
    try:
        if not os.path.exists(_DC_DB_PATH):
            return None
        conn = sqlite3.connect(_DC_DB_PATH, timeout=3)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _query_latest(source: str, sub_category: Optional[str] = None) -> Optional[Dict]:
    """查询某数据源最新一条记录的 metrics"""
    conn = _get_conn()
    if conn is None:
        return None
    try:
        if sub_category:
            cur = conn.execute(
                "SELECT metrics, timestamp FROM records WHERE source=? AND sub_category=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (source, sub_category),
            )
        else:
            cur = conn.execute(
                "SELECT metrics, timestamp FROM records WHERE source=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (source,),
            )
        row = cur.fetchone()
        if row is None:
            return None
        metrics = json.loads(row["metrics"]) if row["metrics"] else {}
        return {"metrics": metrics, "timestamp": row["timestamp"]}
    except Exception:
        return None
    finally:
        conn.close()


def _query_history(source: str, sub_category: Optional[str] = None, limit: int = 30) -> list:
    """查询某数据源最近 N 条记录（用于计算变化趋势）"""
    conn = _get_conn()
    if conn is None:
        return []
    try:
        if sub_category:
            cur = conn.execute(
                "SELECT metrics, timestamp FROM records WHERE source=? AND sub_category=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (source, sub_category, limit),
            )
        else:
            cur = conn.execute(
                "SELECT metrics, timestamp FROM records WHERE source=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (source, limit),
            )
        rows = cur.fetchall()
        result = []
        for row in rows:
            try:
                metrics = json.loads(row["metrics"]) if row["metrics"] else {}
                result.append({"metrics": metrics, "timestamp": row["timestamp"]})
            except Exception:
                continue
        return result
    except Exception:
        return []
    finally:
        conn.close()


# ============================================================
# 各维度数据查询
# ============================================================

def fetch_fear_greed() -> Optional[Dict]:
    """恐惧贪婪指数（0-100，<25极度恐惧，>75极度贪婪）"""
    rec = _query_latest("fear_greed")
    if rec is None:
        return None
    value = rec["metrics"].get("value")
    if value is None:
        return None
    value = float(value)
    # 方向判定：>55 看多，<45 看空，否则中性
    if value >= 55:
        direction = "BULL"
    elif value <= 45:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"
    # 置信度：偏离 50 的程度
    confidence = min(100, abs(value - 50) * 2)
    return {
        "source": "fear_greed",
        "value": value,
        "direction": direction,
        "confidence": round(confidence, 1),
        "timestamp": rec["timestamp"],
        "label": "极度贪婪" if value >= 75 else "贪婪" if value >= 55 else "中性" if value >= 45 else "恐惧" if value >= 25 else "极度恐惧",
    }


def fetch_fear_greed_enhanced() -> Optional[Dict]:
    """增强版恐惧贪婪（动量/资金/波动率/资本流 四维）"""
    rec = _query_latest("fear_greed_enhanced")
    if rec is None:
        return None
    m = rec["metrics"]
    components = {
        "momentum": m.get("momentum", 50),
        "funding": m.get("funding", 50),
        "capital_flow": m.get("capital_flow", 50),
        "volatility": m.get("volatility", 50),
    }
    avg = sum(components.values()) / len(components)
    if avg >= 55:
        direction = "BULL"
    elif avg <= 45:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"
    confidence = min(100, abs(avg - 50) * 2)
    return {
        "source": "fear_greed_enhanced",
        "value": round(avg, 1),
        "direction": direction,
        "confidence": round(confidence, 1),
        "components": components,
        "timestamp": rec["timestamp"],
    }


def fetch_etf_flow() -> Optional[Dict]:
    """BTC ETF 净流入（单位：百万美元）"""
    rec = _query_latest("etf_flow")
    if rec is None:
        return None
    m = rec["metrics"]
    total = m.get("Total") or m.get("total_flow") or 0
    total = float(total)
    # 净流入 > 0 看多，< 0 看空
    if total > 50:
        direction = "BULL"
    elif total < -50:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"
    # 置信度：净流入绝对值归一化
    confidence = min(100, abs(total) / 5)
    return {
        "source": "etf_flow",
        "value": total,
        "direction": direction,
        "confidence": round(confidence, 1),
        "details": {k: v for k, v in m.items() if k not in ("asset", "total_flow")},
        "timestamp": rec["timestamp"],
    }


def fetch_stablecoin_supply() -> Optional[Dict]:
    """稳定币市值变化（USDT+USDC 流通量）"""
    rec = _query_latest("stablecoin_transparency")
    if rec is None:
        return None
    m = rec["metrics"]
    usdt = m.get("usdt_circulating_usd_bln", 0)
    usdc = m.get("usdc_circulating_usd_bln", 0)
    total = usdt + usdc
    change_7d = m.get("change_7d_pct", 0)
    change_30d = m.get("change_30d_pct", 0)
    # 稳定币市值增加 → 购买力增强 → 看多
    if change_7d > 0.5:
        direction = "BULL"
    elif change_7d < -0.5:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"
    confidence = min(100, abs(change_7d) * 20)
    return {
        "source": "stablecoin_transparency",
        "value": round(total, 2),
        "direction": direction,
        "confidence": round(confidence, 1),
        "change_7d_pct": change_7d,
        "change_30d_pct": change_30d,
        "timestamp": rec["timestamp"],
    }


def fetch_funding_rate() -> Optional[Dict]:
    """永续合约资金费率（正=多头付费，负=空头付费）"""
    rec = _query_latest("coinglass", "funding_rate")
    if rec is None:
        return None
    m = rec["metrics"]
    # coinglass funding_rate 数据较简略，尝试从 events 获取
    # 简化：用 item_count 作为信号强度代理
    item_count = m.get("item_count", 0)
    # 无详细资金费率时返回中性
    return {
        "source": "coinglass_funding_rate",
        "value": 0,
        "direction": "NEUTRAL",
        "confidence": 0,
        "item_count": item_count,
        "timestamp": rec["timestamp"],
        "note": "资金费率详细数据待补充",
    }


def fetch_deribit_oi() -> Optional[Dict]:
    """Deribit 期权持仓量（OI）"""
    rec = _query_latest("deribit")
    if rec is None:
        return None
    m = rec["metrics"]
    oi = m.get("oi", 0)
    return {
        "source": "deribit_options",
        "value": float(oi),
        "direction": "NEUTRAL",
        "confidence": 0,
        "timestamp": rec["timestamp"],
    }


def fetch_fred_macro() -> Optional[Dict]:
    """宏观经济指标（美联储利率、CPI、M2）"""
    result = {}
    for sub in ["FEDFUNDS", "CPIAUCSL", "M2SL"]:
        rec = _query_latest("fred", sub)
        if rec:
            result[sub] = {
                "value": rec["metrics"].get("value"),
                "timestamp": rec["timestamp"],
            }
    if not result:
        return None
    # 综合宏观方向：利率下降+M2增加 → 流动性宽松 → 看多
    fedfunds = result.get("FEDFUNDS", {}).get("value")
    m2 = result.get("M2SL", {}).get("value")
    direction = "NEUTRAL"
    confidence = 30.0  # 宏观默认中等置信度
    if fedfunds is not None and m2 is not None:
        # 简化判定：利率低 + M2 高 → 宽松
        if fedfunds < 4.0:
            direction = "BULL"
            confidence = 50.0
        elif fedfunds > 5.0:
            direction = "BEAR"
            confidence = 50.0
    return {
        "source": "fred_macro",
        "direction": direction,
        "confidence": confidence,
        "indicators": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def fetch_defillama_tvl() -> Optional[Dict]:
    """DeFi 总锁仓量（TVL）"""
    rec = _query_latest("defillama")
    if rec is None:
        return None
    m = rec["metrics"]
    tvl = m.get("tvl_bln") or m.get("tvl", 0)
    return {
        "source": "defillama_tvl",
        "value": float(tvl),
        "direction": "NEUTRAL",
        "confidence": 20.0,
        "timestamp": rec["timestamp"],
    }


# ============================================================
# 综合数据获取
# ============================================================

def fetch_all_fundamental_data() -> Dict[str, Any]:
    """一次性获取所有基本面维度数据（FAIL-OPEN）"""
    return {
        "fear_greed": fetch_fear_greed(),
        "fear_greed_enhanced": fetch_fear_greed_enhanced(),
        "etf_flow": fetch_etf_flow(),
        "stablecoin_supply": fetch_stablecoin_supply(),
        "funding_rate": fetch_funding_rate(),
        "deribit_oi": fetch_deribit_oi(),
        "fred_macro": fetch_fred_macro(),
        "defillama_tvl": fetch_defillama_tvl(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    data = fetch_all_fundamental_data()
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
