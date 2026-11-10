"""因素-数据序列映射 — SPEC-D1-MULTIDIM-STATE §7 P2。

把 FACTOR_ONTOLOGY 的 60 细类映射到真实数据序列，并探测实际历史长度：

  long  : ≥900 天 → L1 因素预测力可验证（不依赖文章）
  short : 30-899 天 → 仅 L2/L3 样本内可用
  none  : <30 天或无源 → unverifiable（如实标注，不插值不伪造）

数据源：
  kline  : 18 域 data_center.db records(source='yfinance', sub_category='BTC-USD')
  mm     : 19-DAL mm_metrics(source + metric)
  events : 18 域 backfill/events_d1.jsonl

FAIL-OPEN：探测失败按 0 天处理，不抛。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("data_center.processing.factor_series_map")

AVAILABILITY_RULES = {"long": 900, "short": 30}

# factor_id → {series, source, note, mm_source?, mm_metric?}
SERIES_MAP: dict[str, dict[str, Any]] = {
    # ── technical：全部从 BTC 日 K 派生（长历史）──────────────
    "technical.trend": {
        "series": "kline:ma_spread_20_60",
        "source": "kline",
        "note": "MA20-MA60 价差",
    },
    "technical.momentum": {"series": "kline:rsi14", "source": "kline", "note": "RSI14"},
    "technical.level": {
        "series": "kline:dist_to_high20",
        "source": "kline",
        "note": "距 20 日高/低点距离",
    },
    "technical.volume": {
        "series": "kline:volume_z20",
        "source": "kline",
        "note": "成交量 20 日 z-score",
    },
    "technical.pattern": {
        "series": "kline:atr14_ratio",
        "source": "kline",
        "note": "ATR/价格（形态强度代理，非严格形态识别）",
    },
    "technical.ma_cross": {
        "series": "kline:ma_cross_flag",
        "source": "kline",
        "note": "MA20/MA60 交叉标志",
    },
    "technical.volatility": {
        "series": "kline:rv20",
        "source": "kline",
        "note": "20 日已实现波动率",
    },
    "technical.fib": {
        "series": "kline:retrace_ratio",
        "source": "kline",
        "note": "回撤比例（斐波那契代理）",
    },
    "technical.candlestick": {
        "series": "kline:body_ratio",
        "source": "kline",
        "note": "K 线实体占比",
    },
    "technical.trendline": {
        "series": "kline:slope20",
        "source": "kline",
        "note": "20 日线性斜率",
    },
    # ── flow：DAL 短历史（15-40 天）──────────────────────────
    "flow.funding": {
        "series": "mm:binance_funding_rate.funding_rate.funding_rate_pct",
        "source": "mm",
        "note": "资金费率",
        "mm_source": "binance_funding_rate",
        "mm_sub_category": "funding_rate",
        "mm_metric": "funding_rate_pct",
    },
    "flow.oi": {
        "series": "mm:deribit.options.oi",
        "source": "mm",
        "note": "未平仓合约（Deribit 期权 OI）",
        "mm_source": "deribit",
        "mm_sub_category": "options",
        "mm_metric": "oi",
    },
    "flow.long_short": {
        "series": "mm:binance_futures.long_short_ratio",
        "source": "mm",
        "note": "多空比",
        "mm_source": "binance_futures",
        "mm_sub_category": "long_short_ratio",
    },
    "flow.etf_flow": {"series": None, "source": "none", "note": "无全历史 ETF 净流入源"},
    "flow.stablecoin": {"series": None, "source": "none", "note": "无稳定币增发历史源"},
    "flow.exchange_netflow": {"series": None, "source": "none", "note": "无交易所净流历史源"},
    "flow.whale": {"series": None, "source": "none", "note": "无巨鲸转账历史源"},
    "flow.liquidation": {"series": None, "source": "none", "note": "mm 无 liquidation 序列"},
    "flow.taker": {"series": None, "source": "none", "note": "mm 无 taker_volume 序列"},
    "flow.etf_premium": {"series": None, "source": "none", "note": "无 GBTC 溢价历史源"},
    # ── onchain：DAL 短历史（40-41 天）───────────────────────
    "onchain.active_addr": {
        "series": "mm:blockchain_info.btc_basics.active_addresses",
        "source": "mm",
        "note": "活跃地址数",
        "mm_source": "blockchain_info",
        "mm_sub_category": "btc_basics",
        "mm_metric": "active_addresses",
    },
    "onchain.hashrate": {
        "series": "mm:blockchain_info.btc_basics.hashrate",
        "source": "mm",
        "note": "哈希率",
        "mm_source": "blockchain_info",
        "mm_sub_category": "btc_basics",
        "mm_metric": "hashrate",
    },
    "onchain.mvrv": {"series": None, "source": "none", "note": "bgeometrics 未按指标细分"},
    "onchain.sopr": {"series": None, "source": "none", "note": "bgeometrics 未按指标细分"},
    "onchain.nupl": {"series": None, "source": "none", "note": "bgeometrics 未按指标细分"},
    "onchain.holder": {"series": None, "source": "none", "note": "无持币分布历史源"},
    "onchain.tvl": {
        "series": "mm:defillama.all_protocols",
        "source": "mm",
        "note": "DeFi 总锁仓",
        "mm_source": "defillama",
        "mm_sub_category": "all_protocols",
    },
    "onchain.gas": {"series": None, "source": "none", "note": "无 Gas 费历史源"},
    "onchain.exchange_supply": {"series": None, "source": "none", "note": "无交易所存量历史源"},
    "onchain.realized_cap": {"series": None, "source": "none", "note": "bgeometrics 未按指标细分"},
    # ── macro：fred 长历史 ──────────────────────────────────
    "macro.rate": {
        "series": "mm:fred.DGS10",
        "source": "mm",
        "note": "10 年期美债收益率（市场利率代理）",
        "mm_source": "fred",
        "mm_sub_category": "DGS10",
    },
    "macro.inflation": {
        "series": "mm:fred.CPIAUCSL",
        "source": "mm",
        "note": "CPI",
        "mm_source": "fred",
        "mm_sub_category": "CPIAUCSL",
    },
    "macro.employment": {
        "series": "mm:fred.PAYEMS",
        "source": "mm",
        "note": "非农就业",
        "mm_source": "fred",
        "mm_sub_category": "PAYEMS",
    },
    "macro.liquidity": {
        "series": "mm:fred.WALCL",
        "source": "mm",
        "note": "美联储资产负债表",
        "mm_source": "fred",
        "mm_sub_category": "WALCL",
    },
    "macro.dollar": {
        "series": "mm:fred.DTWEXBGS",
        "source": "mm",
        "note": "美元指数",
        "mm_source": "fred",
        "mm_sub_category": "DTWEXBGS",
    },
    "macro.treasury": {
        "series": "mm:fred.T10Y2Y",
        "source": "mm",
        "note": "期限利差",
        "mm_source": "fred",
        "mm_sub_category": "T10Y2Y",
    },
    "macro.equity": {
        "series": "mm:fred.NASDAQCOM",
        "source": "mm",
        "note": "纳斯达克指数",
        "mm_source": "fred",
        "mm_sub_category": "NASDAQCOM",
    },
    "macro.gdp": {
        "series": "mm:fred.INDPRO",
        "source": "mm",
        "note": "工业生产指数（GDP 代理）",
        "mm_source": "fred",
        "mm_sub_category": "INDPRO",
    },
    "macro.central_bank": {
        "series": "mm:fred.FEDFUNDS",
        "source": "mm",
        "note": "联邦基金利率（仅美联储口径，欧/日/中无源）",
        "mm_source": "fred",
        "mm_sub_category": "FEDFUNDS",
    },
    "macro.credit": {
        "series": "mm:fred.BAMLH0A0HYM2",
        "source": "mm",
        "note": "高收益债利差",
        "mm_source": "fred",
        "mm_sub_category": "BAMLH0A0HYM2",
    },
    # ── event：事件库（2023-01 起）──────────────────────────
    "event.regulation": {
        "series": "events:regulation.crypto",
        "source": "events",
        "note": "加密监管事件",
    },
    "event.etf_approval": {
        "series": "events:etf.regulation",
        "source": "events",
        "note": "ETF 审批事件",
    },
    "event.hack": {"series": "events:hack.security", "source": "events", "note": "安全事件"},
    "event.unlock": {"series": "events:unlock.supply", "source": "events", "note": "代币解锁"},
    "event.listing": {
        "series": "events:listing.exchange",
        "source": "events",
        "note": "交易所上线",
    },
    "event.partnership": {"series": None, "source": "none", "note": "事件库无合作类"},
    "event.funding_round": {"series": None, "source": "none", "note": "事件库无融资类"},
    "event.legal": {"series": None, "source": "none", "note": "事件库无诉讼类"},
    "event.upgrade": {"series": None, "source": "none", "note": "事件库无升级类"},
    "event.airdrop": {"series": None, "source": "none", "note": "事件库无空投类"},
    # ── sentiment ──────────────────────────────────────────
    "sentiment.fear_greed": {"series": None, "source": "none", "note": "mm 无 alternative 源"},
    "sentiment.social_heat": {"series": None, "source": "none", "note": "社交量仅 24 天，不足"},
    "sentiment.narrative": {
        "series": None,
        "source": "none",
        "note": "依赖 39 域 S1 主题聚类回填（P1 未做）",
    },
    "sentiment.retail": {"series": None, "source": "none", "note": "无散户情绪源"},
    "sentiment.institutional": {"series": None, "source": "none", "note": "无机构持仓源"},
    "sentiment.analyst": {"series": None, "source": "none", "note": "无研报源"},
    "sentiment.community": {"series": None, "source": "none", "note": "无社区活跃度源"},
    "sentiment.halving": {"series": None, "source": "none", "note": "减半日历可手工补，暂缺"},
    "sentiment.cycle": {
        "series": "kline:trend_200",
        "source": "kline",
        "note": "200 日均线趋势（周期代理）",
    },
    "sentiment.altseason": {"series": None, "source": "none", "note": "无山寨季指数源"},
}


def classify_availability(days: int) -> str:
    """天数 → long / short / none。"""
    try:
        d = int(days)
    except (TypeError, ValueError):
        return "none"
    if d >= AVAILABILITY_RULES["long"]:
        return "long"
    if d >= AVAILABILITY_RULES["short"]:
        return "short"
    return "none"


def _ro_conn(db: Any) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except Exception:  # noqa: BLE003
        return None


def _probe_kline_days(db: Any) -> int:
    """BTC 日 K 天数。"""
    conn = _ro_conn(db)
    if conn is None:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM records " "WHERE source='yfinance' AND sub_category='BTC-USD'"
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE003
        return 0
    finally:
        conn.close()


def _probe_mm_days(
    db: Any, source: str | None, sub_category: str | None, metric: str | None = None
) -> int:
    """mm_metrics 某 source + sub_category(+metric_name) 的不同日期数。"""
    if not source:
        return 0
    conn = _ro_conn(db)
    if conn is None:
        return 0
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mm_metrics)")]
        if not cols:
            return 0
        tcol = next((c for c in ("timestamp", "ts", "date", "time") if c in cols), None)
        if tcol is None:
            return 0
        date_expr = (
            f"date({tcol},'unixepoch')" if tcol in ("timestamp", "ts") else f"substr({tcol},1,10)"
        )
        sql = f"SELECT COUNT(DISTINCT {date_expr}) FROM mm_metrics WHERE source=?"
        args: list[Any] = [source]
        if sub_category:
            sql += " AND sub_category=?"
            args.append(sub_category)
        if metric:
            sql += " AND metric_name=?"
            args.append(metric)
        row = conn.execute(sql, tuple(args)).fetchone()
        return int(row[0]) if row and row[0] else 0
    except Exception:  # noqa: BLE003
        return 0
    finally:
        conn.close()


def _probe_event_days(jsonl: Any) -> int:
    """事件库时间跨度（天）。"""
    try:
        p = Path(jsonl)
        if not p.exists():
            return 0
        ts_min = ts_max = None
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                ts = json.loads(line).get("trigger_ts")
            except ValueError:
                continue
            if not isinstance(ts, (int, float)):
                continue
            ts = int(ts)
            ts_min = ts if ts_min is None else min(ts_min, ts)
            ts_max = ts if ts_max is None else max(ts_max, ts)
        if ts_min is None or ts_max is None:
            return 0
        return max(0, (ts_max - ts_min) // 86400)
    except Exception:  # noqa: BLE003
        return 0


def build_series_map(mm_db: Any, kline_db: Any, event_jsonl: Any) -> dict:
    """探测真实数据长度并生成映射结果。FAIL-OPEN。"""
    try:
        kline_days = _probe_kline_days(kline_db)
        event_days = _probe_event_days(event_jsonl)
        # mm 探测结果缓存（同 source+metric 只查一次）
        mm_cache: dict[tuple, int] = {}

        factors: dict[str, dict] = {}
        counts = {"long": 0, "short": 0, "none": 0}
        for fid, m in SERIES_MAP.items():
            src = m["source"]
            if src == "kline":
                days = kline_days
            elif src == "events":
                days = event_days
            elif src == "mm":
                key = (m.get("mm_source"), m.get("mm_sub_category"), m.get("mm_metric"))
                if key not in mm_cache:
                    mm_cache[key] = _probe_mm_days(mm_db, key[0], key[1], key[2])
                days = mm_cache[key]
            else:
                days = 0
            avail = classify_availability(days)
            counts[avail] += 1
            factors[fid] = {
                "series": m["series"],
                "source": src,
                "note": m["note"],
                "days": days,
                "availability": avail,
                "l1_verifiable": avail == "long",
                "l2l3_usable": avail in ("long", "short"),
            }

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_factors": len(SERIES_MAP),
            "l1_verifiable": counts["long"],
            "l2l3_usable": counts["long"] + counts["short"],
            "unverifiable": counts["none"],
            "counts": counts,
            "kline_days": kline_days,
            "event_span_days": event_days,
            "factors": factors,
        }
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] build_series_map 异常 %s: %s", type(e).__name__, str(e)[:200])
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_factors": len(SERIES_MAP),
            "l1_verifiable": 0,
            "l2l3_usable": 0,
            "unverifiable": len(SERIES_MAP),
            "counts": {"long": 0, "short": 0, "none": len(SERIES_MAP)},
            "kline_days": 0,
            "event_span_days": 0,
            "factors": {},
        }
