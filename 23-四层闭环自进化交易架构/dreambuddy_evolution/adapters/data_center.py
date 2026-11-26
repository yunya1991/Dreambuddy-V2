"""
DataCenterAdapter — 从 data_center.db 查询 panewslab 采集的衍生品数据
SPEC §2.2

FAIL-OPEN: 查询失败/表不存在/无数据 → 返回空 dict
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import time
from typing import Any

from ..core.safe_call import safe_call

logger = logging.getLogger(__name__)

# 查询超时 2s
_DB_TIMEOUT = 2.0

_TAG_RE = re.compile(r"<[^>]+>")

# panewslab 在 metrics 中扁平化出的 per-coin 键：fut1_BTC_liq24 / fut1_BTC_oi
_COIN_METRIC_RE = re.compile(r"^fut\d+_([A-Z0-9]+)_(liq24|oi)$")


def _read_pg_password() -> str:
    """读取 18 域 PostgreSQL 密码（与 sink_postgres 同一来源）。"""
    for path in ("/home/luke/.dreambuddy-pg.env", os.path.expanduser("~/.dreambuddy-pg.env")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DATA_CENTER_PG_PASSWORD="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return ""


def resolve_pg_dsn() -> str | None:
    """解析 PostgreSQL DSN；未启用或缺少密码时返回 None（回退 sqlite）。"""
    dsn = os.environ.get("DATA_CENTER_PG_DSN", "").strip()
    if dsn:
        return dsn
    flag = os.environ.get("EVOLUTION_DATA_CENTER_PG", "").strip().lower()
    if flag not in ("1", "true", "on", "yes"):
        return None
    pwd = os.environ.get("DATA_CENTER_PG_PASSWORD", "").strip() or _read_pg_password()
    if not pwd:
        logger.warning("[FO] EVOLUTION_DATA_CENTER_PG 开启但缺少密码，回退 sqlite")
        return None
    host = os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1")
    port = os.environ.get("DATA_CENTER_PG_PORT", "5432")
    user = os.environ.get("DATA_CENTER_PG_USER", "dreambuddy")
    db = os.environ.get("DATA_CENTER_PG_DB", "data_center")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


def _parse_metrics(record: dict) -> dict:
    """metrics/timeseries 字段 JSON 解析（TEXT 列），失败保留原值。"""
    for key in ("metrics", "timeseries"):
        if key in record and isinstance(record[key], str):
            record[key] = safe_call(json.loads, record[key], record[key])
    return record


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text)).strip()


class DataCenterAdapter:
    """data_center 数据适配器（PostgreSQL records 表 / sqlite 兼容回退）"""

    def __init__(self, db_path: str | None = None, pg_dsn: str | None = None) -> None:
        self._db_path = db_path
        self._dsn = pg_dsn if pg_dsn is not None else resolve_pg_dsn()
        self._last_liq_total: float | None = None  # 兼容旧调用方（DB 双记录优先）
        self._last_query_ts: float = 0.0

    # ------------------------------------------------------------------
    # 连接与查询（postgres 走 %s 占位符，sqlite 走 ?）
    # ------------------------------------------------------------------
    def _connect(self) -> tuple[Any, bool]:
        if self._dsn:
            import psycopg2

            return psycopg2.connect(self._dsn, connect_timeout=int(_DB_TIMEOUT)), True
        if not self._db_path:
            raise sqlite3.OperationalError("no data_center backend configured")
        conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        return conn, False

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        conn, is_pg = self._connect()
        try:
            if is_pg:
                from psycopg2.extras import RealDictCursor

                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(sql.replace("?", "%s"), params)
                return [dict(r) for r in cur.fetchall()]
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def query_latest_derivatives(self, symbol: str | None = None) -> dict[str, Any]:
        """
        查询最新 panewslab 衍生品数据。

        Args:
            symbol: 可选 — 匹配特定币种（BTC/ETH/SOL）的 per-coin 清算数据

        Returns dict (查询失败返回空 dict):
            liquidation_buy: list[float]   — 多方清算额（归一化为单元素数组供 ResistanceVector）
            liquidation_sell: list[float]  — 空方清算额
            liq_index_change: float         — 清算指数变化比 (0.0=无变化, 1.0=翻倍)
            open_interest: float           — 未平仓合约总额
        """
        out: dict[str, Any] = {}
        try:
            records = self._query_latest_records(limit=2)
            if not records:
                return out

            record = records[0]
            metrics = record.get("metrics", {}) if isinstance(record, dict) else {}

            # 全局清算
            liq_long = metrics.get("fut_liq_long_24h_usd")
            liq_short = metrics.get("fut_liq_short_24h_usd")
            liq_total = metrics.get("fut_liq_total_24h_usd")
            oi = metrics.get("fut_open_interest_usd")

            # per-coin 匹配（如果提供了 symbol）
            if symbol:
                coin_data = self._extract_per_coin(record, symbol)
                if coin_data.get("long_liq") is not None:
                    liq_long = coin_data["long_liq"]
                if coin_data.get("short_liq") is not None:
                    liq_short = coin_data["short_liq"]
                if coin_data.get("oi"):
                    oi = coin_data["oi"]

            if liq_long is not None:
                out["liquidation_buy"] = [float(liq_long)]
            if liq_short is not None:
                out["liquidation_sell"] = [float(liq_short)]
            if oi is not None:
                out["open_interest"] = float(oi)

            # liq_index_change: 与上一条采集记录比较（跨进程确定，冷启动即有值）
            if liq_total is not None:
                total = float(liq_total)
                prev_total = None
                if len(records) > 1:
                    prev_metrics = records[1].get("metrics", {}) or {}
                    if isinstance(prev_metrics, dict):
                        prev_total = prev_metrics.get("fut_liq_total_24h_usd")
                if prev_total is None:
                    prev_total = self._last_liq_total
                if prev_total is not None and float(prev_total) > 0:
                    change = (total - float(prev_total)) / float(prev_total)
                    out["liq_index_change"] = max(-1.0, min(2.0, change))
                else:
                    out["liq_index_change"] = 0.0
                self._last_liq_total = total
                self._last_query_ts = time.time()

        except Exception as e:
            logger.warning("[FO] DataCenterAdapter query crash: %s", e)

        return out

    def _query_latest_records(self, limit: int = 1) -> list[dict]:
        """查询最近 N 条 panewslab derivatives 记录（PG records / sqlite 兼容）"""
        try:
            rows = self._query(
                "SELECT * FROM records "
                "WHERE source = 'panewslab' AND sub_category = 'derivatives_spot' "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [_parse_metrics(dict(r)) for r in rows]
        except Exception as e:
            logger.debug("[FO] data_center query fail: %s", e)
            return []

    def _query_latest_record(self) -> dict | None:
        """查询最新 panewslab derivatives 记录"""
        recs = self._query_latest_records(limit=1)
        return recs[0] if recs else None

    @staticmethod
    def _extract_per_coin(record: dict, symbol: str) -> dict[str, float | None]:
        """提取特定币种的清算/持仓数据。

        优先 timeseries.futures_markets（含多空拆分）；
        回退 metrics 扁平键 fut{N}_{SYM}_liq24 / fut{N}_{SYM}_oi（云端 PG 实际形态，
        仅含总额 → 按全局多空占比拆分）。
        """
        try:
            sym_upper = symbol.upper()
            timeseries = record.get("timeseries", [])
            if isinstance(timeseries, list):
                for ts in timeseries:
                    if not isinstance(ts, dict) or ts.get("name") != "futures_markets":
                        continue
                    items = ts.get("items", [])
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        item_sym = str(item.get("symbol", "")).upper()
                        if item_sym == sym_upper or (item_sym and sym_upper in item_sym):
                            return {
                                "long_liq": float(item.get("long_liq_usd_24h", 0) or 0),
                                "short_liq": float(item.get("short_liq_usd_24h", 0) or 0),
                                "oi": float(item.get("open_interest_usd", 0) or 0),
                            }

            metrics = record.get("metrics", {}) if isinstance(record, dict) else {}
            if not isinstance(metrics, dict):
                return {}
            coin: dict[str, float | None] = {}
            for key, val in metrics.items():
                m = _COIN_METRIC_RE.match(str(key))
                if not m or m.group(1) != sym_upper:
                    continue
                try:
                    coin["oi" if m.group(2) == "oi" else "total_liq"] = float(val)
                except (TypeError, ValueError):
                    continue
            if not coin:
                return {}
            # 仅有总额时按全局多空占比拆分（panewslab 不提供 per-coin 多空）
            if "total_liq" in coin:
                total_liq = coin["total_liq"] or 0.0
                g_long = float(metrics.get("fut_liq_long_24h_usd", 0) or 0)
                g_short = float(metrics.get("fut_liq_short_24h_usd", 0) or 0)
                denom = g_long + g_short
                share = g_long / denom if denom > 0 else 0.5
                coin["long_liq"] = total_liq * share
                coin["short_liq"] = total_liq * (1.0 - share)
            return coin
        except Exception as e:
            logger.debug("[FO] per-coin extract fail: %s", e)

        return {}

    def query_recent_newsflash(self, limit: int = 20, hours: int = 0) -> list[dict]:
        """查询最近快讯（odaily_newsflash 为主，odaily/newsflash 为兼容回退）。

        Returns: [{timestamp, text, event_type}]，text 已去 HTML 标签。
        """
        rows: list[dict] = []
        try:
            rows = self._query(
                "SELECT timestamp, metrics FROM records "
                "WHERE source = 'odaily_newsflash' ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        except Exception as e:
            logger.debug("[FO] newsflash query fail: %s", e)
        if not rows:
            try:
                rows = self._query(
                    "SELECT timestamp, metrics FROM records "
                    "WHERE source = 'odaily' AND sub_category = 'newsflash' "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            except Exception as e:
                logger.debug("[FO] legacy newsflash query fail: %s", e)

        out: list[dict] = []
        for row in rows:
            rec = _parse_metrics(dict(row))
            m = rec.get("metrics")
            if isinstance(m, str):
                m = safe_call(json.loads, m, {})
            if not isinstance(m, dict):
                continue
            text = m.get("description") or m.get("title") or m.get("content") or m.get("text") or ""
            text = _strip_html(str(text))
            if not text:
                continue
            out.append(
                {
                    "timestamp": rec.get("timestamp", ""),
                    "text": text,
                    "event_type": m.get("od_event_type", ""),
                }
            )
        return out

    # ================================================================
    # 🆕 P1: 扩展查询 — ETF/情绪/链上/期权/机构持仓
    # ================================================================
    def query_etf_flow(self) -> dict[str, float]:
        """查询最新 ETF 净流入/流出（AGI Phase4.3）。"""
        return self._query_latest_by_source("etf_flow", "finance")

    def query_fear_greed(self) -> dict[str, float]:
        """查询最新 F&G 指数（AGI L1 感知层情绪因子）。"""
        out: dict[str, float] = {}
        rec = self._query_latest_record_by_source("fear_greed", "chain")
        if rec:
            m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
            for k in ("value", "fear_greed_value"):
                if k in m:
                    try:
                        out["fear_greed"] = float(m[k])
                    except (ValueError, TypeError) as e:
                        # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                        logger.debug("[FO] fear_greed float convert fail: %s", e)
                    break
        return out

    def query_btc_onchain(self) -> dict[str, float]:
        """查询最新 BTC 链上深度指标（MVRV/SOPR/NUPL/难度/哈希率）。"""
        out: dict[str, float] = {}
        # bgeometrics
        rec = self._query_latest_record_by_source("bgeometrics", "chain")
        if rec:
            m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
            for k in (
                "mvrv",
                "sopr",
                "nupl",
                "active_addresses",
                "exchange_netflow",
                "puell_multiple",
            ):
                if k in m:
                    try:
                        out[k] = float(m[k])
                    except (ValueError, TypeError) as e:
                        # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                        logger.debug("[FO] btc_onchain float convert fail: %s", e)
        # mempool
        rec2 = self._query_latest_record_by_source("mempool", "chain")
        if rec2:
            m2 = rec2.get("metrics", {}) if isinstance(rec2, dict) else {}
            for k in ("tip_height", "mempool_count", "difficulty_change_pct"):
                if k in m2:
                    try:
                        out[k] = float(m2[k])
                    except (ValueError, TypeError) as e:
                        # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                        logger.debug("[FO] mempool float convert fail: %s", e)
        return out

    def query_options(self) -> dict[str, float]:
        """查询最新 Deribit 期权数据（Max Pain/P-C Ratio/OI）。"""
        return self._query_latest_by_source("deribit", "chain")

    def query_cot(self) -> dict[str, float]:
        """查询最新 CFTC COT 机构持仓。"""
        out: dict[str, float] = {}
        rec = self._query_latest_record_by_source("cftc_cot", "finance")
        if rec:
            m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
            for k in ("non_comm_long", "non_comm_short", "non_comm_net"):
                if k in m:
                    try:
                        out[k] = float(m[k])
                    except (ValueError, TypeError) as e:
                        # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                        logger.debug("[FO] cot float convert fail: %s", e)
        return out

    def query_coinglass_derivatives(self) -> dict[str, float]:
        """查询最新 Coinglass 衍生品聚合数据（OI/Funding/清算/多空比）。"""
        out: dict[str, float] = {}
        for sub in ("open_interest", "funding_rate", "liquidations", "long_short_ratio"):
            rec = self._query_latest_record_by_source("coinglass", "chain", sub)
            if rec:
                m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
                for k, v in m.items():
                    if isinstance(v, (int, float)):
                        try:
                            out[f"{sub}_{k}"] = float(v)
                        except (ValueError, TypeError) as e:
                            # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                            logger.debug("[FO] coinglass float convert fail: %s", e)
        return out

    # ================================================================
    # 🆕 Phase 9: 事件驱动策略 — 经济日历 / FedWatch / FOMC 日历查询
    # ================================================================
    def query_economic_calendar(self) -> dict[str, Any]:
        """查询最新 CPI/NFP/PPI actual/forecast/surprise（event_context 注入用）。

        Returns dict keyed by indicator (cpi/nfp/ppi)，每项含
        actual/forecast/surprise/previous/cesi?/release_date?/_record_timestamp。
        FAIL-OPEN: 查询失败返回空 dict。
        """
        out: dict[str, Any] = {}
        for indicator in ("cpi", "nfp", "ppi"):
            rec = self._query_latest_record_by_source("econ_calendar", "macro", indicator)
            if not rec:
                continue
            m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
            entry: dict[str, Any] = {}
            for k in ("actual", "forecast", "surprise", "previous"):
                if k in m:
                    try:
                        entry[k] = float(m[k])
                    except (ValueError, TypeError) as e:
                        # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                        logger.debug("[FO] econ_calendar float convert fail: %s", e)
            if "cesi" in m:
                try:
                    entry["cesi"] = float(m["cesi"])
                except (ValueError, TypeError) as e:
                    # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                    logger.debug("[FO] econ_calendar cesi convert fail: %s", e)
            if "release_date" in m:
                entry["release_date"] = m["release_date"]
            entry["_record_timestamp"] = rec.get("timestamp", "")
            if entry:
                out[indicator] = entry
        return out

    def query_fedwatch(self) -> dict[str, Any]:
        """查询最新 CME FedWatch 加息/降息概率 + 下次 FOMC 会议日期。

        cme-fedwatch 包返回 effr/current_target 但不含 meeting_date；
        investing.com 降级路径返回 meeting_date/target_rate。
        本方法取最新记录的概率 + 最近含 meeting_date 的记录的会议日期（合并）。

        Returns dict with hike_prob/cut_prob/hold_prob/meeting_date?/effr?。
        FAIL-OPEN: 查询失败返回空 dict。
        """
        out: dict[str, Any] = {}
        # 取最新记录（概率值）
        rec = self._query_latest_record_by_source("cme", "macro", "fedwatch")
        if not rec:
            return out
        m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
        for k in ("hike_prob", "cut_prob", "hold_prob", "effr"):
            if k in m:
                try:
                    out[k] = float(m[k])
                except (ValueError, TypeError) as e:
                    # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                    logger.debug("[FO] fedwatch float convert fail: %s", e)
        for k in ("meeting_date", "target_rate", "current_target", "trade_date"):
            if k in m:
                out[k] = m[k]
        out["_record_timestamp"] = rec.get("timestamp", "")

        # meeting_date 缺失时，查最近 5 条记录中含 meeting_date 的
        if "meeting_date" not in out or not out.get("meeting_date"):
            try:
                rows = self._query(
                    "SELECT * FROM records "
                    "WHERE source = 'cme' AND sub_category = 'fedwatch' "
                    "AND metrics LIKE '%meeting_date%' "
                    "ORDER BY timestamp DESC LIMIT 1"
                )
                if rows:
                    d = _parse_metrics(dict(rows[0]))
                    m2 = d.get("metrics", {})
                    if isinstance(m2, str):
                        m2 = safe_call(json.loads, m2, {})
                    md = m2.get("meeting_date", "") if isinstance(m2, dict) else ""
                    if md:
                        out["meeting_date"] = md
            except Exception as e:
                logger.debug("[FO] fedwatch meeting_date fallback fail: %s", e)
        return out

    def query_fomc_calendar(self) -> list[dict[str, Any]]:
        """查询 FOMC 会议日历记录（供 EventWindowTracker 判定 next/last FOMC）。

        Returns list of {meeting_date, timestamp} 按时间升序。
        FAIL-OPEN: 查询失败返回空列表。
        """
        out: list[dict[str, Any]] = []
        try:
            rows = self._query(
                "SELECT * FROM records "
                "WHERE source = 'cme' AND sub_category = 'fomc_calendar' "
                "ORDER BY timestamp ASC"
            )
            for row in rows:
                d = dict(row)
                raw = d.get("raw", "{}")
                if isinstance(raw, str):
                    raw = safe_call(json.loads, raw, {})
                meeting_date = ""
                if isinstance(raw, dict):
                    meeting_date = raw.get("meeting_date", "")
                out.append(
                    {
                        "meeting_date": meeting_date,
                        "timestamp": d.get("timestamp", ""),
                    }
                )
        except Exception as e:
            logger.debug("[FO] query_fomc_calendar fail: %s", e)
        return out

    def query_coinmarketcal_events(self) -> list[dict[str, Any]]:
        """查询 CoinMarketCal 加密事件记录（tech_upgrade 等，供 GeneralEventWindowTracker）。

        SPEC-Phase2 §6.1: source=coinmarketcal, category=protocol, sub_category=tech_upgrade。
        取 metrics.event_date + metrics.direction + metrics.title 用于窗口判定。

        Returns list of {event_date(str), direction(str), title(str), timestamp(str)} 按事件日期升序。
        FAIL-OPEN: 查询失败返回空列表。
        """
        out: list[dict[str, Any]] = []
        try:
            rows = self._query(
                "SELECT * FROM records "
                "WHERE source = 'coinmarketcal' AND sub_category = 'tech_upgrade' "
                "ORDER BY timestamp DESC LIMIT 20"
            )
            for row in rows:
                d = dict(row)
                m = d.get("metrics", "{}")
                if isinstance(m, str):
                    m = safe_call(json.loads, m, {})
                if not isinstance(m, dict):
                    continue
                event_date = m.get("date_event", "") or m.get("event_date", "")
                if not event_date:
                    continue
                out.append(
                    {
                        "event_date": event_date,
                        "direction": m.get("direction", "neutral"),
                        "title": m.get("title", ""),
                        "timestamp": d.get("timestamp", ""),
                    }
                )
            out.sort(key=lambda x: x.get("event_date", ""))
        except Exception as e:
            logger.debug("[FO] query_coinmarketcal_events fail: %s", e)
        return out

    def query_congressional_hearings(self) -> list[dict[str, Any]]:
        """查询国会听证会记录（congressional_hearing，供 GeneralEventWindowTracker）。

        SPEC-Phase2 §6.4: source=congress, category=macro, sub_category=congressional_hearing。
        取 metrics.date_event + metrics.direction + metrics.title 用于窗口判定。

        Returns list of {event_date(str), direction(str), title(str), timestamp(str)} 按事件日期升序。
        FAIL-OPEN: 查询失败返回空列表。
        """
        out: list[dict[str, Any]] = []
        try:
            rows = self._query(
                "SELECT * FROM records "
                "WHERE source = 'congress' AND sub_category = 'congressional_hearing' "
                "ORDER BY timestamp DESC LIMIT 20"
            )
            for row in rows:
                d = dict(row)
                m = d.get("metrics", "{}")
                if isinstance(m, str):
                    m = safe_call(json.loads, m, {})
                if not isinstance(m, dict):
                    continue
                event_date = m.get("date_event", "") or m.get("event_date", "")
                if not event_date:
                    continue
                out.append(
                    {
                        "event_date": event_date,
                        "direction": m.get("direction", "neutral"),
                        "title": m.get("title", ""),
                        "timestamp": d.get("timestamp", ""),
                    }
                )
            out.sort(key=lambda x: x.get("event_date", ""))
        except Exception as e:
            logger.debug("[FO] query_congressional_hearings fail: %s", e)
        return out

    def _query_latest_by_source(self, source: str, category: str) -> dict[str, float]:
        """通用：按 source 查最新 record，提取数值 metrics。"""
        rec = self._query_latest_record_by_source(source, category)
        if not rec:
            return {}
        m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
        out: dict[str, float] = {}
        for k, v in m.items():
            if isinstance(v, (int, float)):
                try:
                    out[k] = float(v)
                except (ValueError, TypeError) as e:
                    # 类型容错 FAIL-OPEN: 转换失败则跳过该字段
                    logger.debug("[FO] metrics float convert fail: %s", e)
        return out

    def _query_latest_record_by_source(
        self, source: str, category: str, sub_category: str | None = None
    ) -> dict | None:
        """查询最新 record by source/category/sub_category。"""
        try:
            if sub_category:
                rows = self._query(
                    "SELECT * FROM records "
                    "WHERE source = ? AND category = ? AND sub_category = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (source, category, sub_category),
                )
            else:
                rows = self._query(
                    "SELECT * FROM records "
                    "WHERE source = ? AND category = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (source, category),
                )
            if not rows:
                return None
            return _parse_metrics(dict(rows[0]))
        except Exception as e:
            logger.debug("[FO] query_latest_record_by_source fail: %s", e)
            return None
