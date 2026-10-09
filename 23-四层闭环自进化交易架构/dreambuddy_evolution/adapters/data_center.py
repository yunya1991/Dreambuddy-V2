"""
DataCenterAdapter — 从 data_center.db 查询 panewslab 采集的衍生品数据
SPEC §2.2

FAIL-OPEN: 查询失败/表不存在/无数据 → 返回空 dict
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

# 查询超时 2s
_DB_TIMEOUT = 2.0


class DataCenterAdapter:
    """data_center.db 衍生品数据适配器"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._last_liq_total: float | None = None  # 上次清算总额（计算 liq_index_change）
        self._last_query_ts: float = 0.0

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
            record = self._query_latest_record()
            if record is None:
                return out

            metrics = record.get("metrics", {}) if isinstance(record, dict) else {}

            # 全局清算
            liq_long = metrics.get("fut_liq_long_24h_usd")
            liq_short = metrics.get("fut_liq_short_24h_usd")
            liq_total = metrics.get("fut_liq_total_24h_usd")
            oi = metrics.get("fut_open_interest_usd")

            # per-coin 匹配（如果提供了 symbol）
            if symbol:
                coin_data = self._extract_per_coin(record, symbol)
                if coin_data:
                    liq_long = coin_data.get("long_liq", liq_long)
                    liq_short = coin_data.get("short_liq", liq_short)

            if liq_long is not None:
                out["liquidation_buy"] = [float(liq_long)]
            if liq_short is not None:
                out["liquidation_sell"] = [float(liq_short)]
            if oi is not None:
                out["open_interest"] = float(oi)

            # liq_index_change: 当前 vs 上次的变化比
            if liq_total is not None:
                total = float(liq_total)
                now = time.time()
                if self._last_liq_total is not None and self._last_liq_total > 0:
                    change = (total - self._last_liq_total) / self._last_liq_total
                    out["liq_index_change"] = max(-1.0, min(2.0, change))
                self._last_liq_total = total
                self._last_query_ts = now

        except Exception as e:
            logger.warning("[FO] DataCenterAdapter query crash: %s", e)

        return out

    def _query_latest_record(self) -> dict | None:
        """查询最新 panewslab derivatives 记录"""
        try:
            conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # data_center.db 表名可能是 records 或 data_records
            cursor.execute(
                "SELECT * FROM records "
                "WHERE source = 'panewslab' AND sub_category = 'derivatives_spot' "
                "ORDER BY timestamp DESC LIMIT 1"
            )
            row = cursor.fetchone()
            conn.close()

            if row is None:
                return None

            # 将 Row 转为 dict，解析 metrics/timeseries JSON
            d = dict(row)
            for key in ("metrics", "timeseries"):
                if key in d and isinstance(d[key], str):
                    try:
                        d[key] = json.loads(d[key])
                    except Exception:
                        pass
            return d

        except sqlite3.OperationalError as e:
            logger.debug("[FO] data_center DB query fail: %s", e)
            return None
        except Exception as e:
            logger.warning("[FO] data_center DB unexpected: %s", e)
            return None

    @staticmethod
    def _extract_per_coin(record: dict, symbol: str) -> dict[str, float]:
        """从 timeseries 中提取特定币种的清算数据"""
        try:
            timeseries = record.get("timeseries", [])
            if not isinstance(timeseries, list):
                return {}

            sym_upper = symbol.upper()
            for ts in timeseries:
                if not isinstance(ts, dict):
                    continue
                if ts.get("name") != "futures_markets":
                    continue

                items = ts.get("items", [])
                if not isinstance(items, list):
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if (item.get("symbol", "").upper() == sym_upper
                            or sym_upper in (item.get("symbol", "").upper())):
                        return {
                            "long_liq": float(item.get("long_liq_usd_24h", 0) or 0),
                            "short_liq": float(item.get("short_liq_usd_24h", 0) or 0),
                            "oi": float(item.get("open_interest_usd", 0) or 0),
                        }
        except Exception as e:
            logger.debug("[FO] per-coin extract fail: %s", e)

        return {}

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
                    except (ValueError, TypeError):
                        pass
                    break
        return out

    def query_btc_onchain(self) -> dict[str, float]:
        """查询最新 BTC 链上深度指标（MVRV/SOPR/NUPL/难度/哈希率）。"""
        out: dict[str, float] = {}
        # bgeometrics
        rec = self._query_latest_record_by_source("bgeometrics", "chain")
        if rec:
            m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
            for k in ("mvrv", "sopr", "nupl", "active_addresses", "exchange_netflow", "puell_multiple"):
                if k in m:
                    try:
                        out[k] = float(m[k])
                    except (ValueError, TypeError):
                        pass
        # mempool
        rec2 = self._query_latest_record_by_source("mempool", "chain")
        if rec2:
            m2 = rec2.get("metrics", {}) if isinstance(rec2, dict) else {}
            for k in ("tip_height", "mempool_count", "difficulty_change_pct"):
                if k in m2:
                    try:
                        out[k] = float(m2[k])
                    except (ValueError, TypeError):
                        pass
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
                    except (ValueError, TypeError):
                        pass
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
                        except (ValueError, TypeError):
                            pass
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
            rec = self._query_latest_record_by_source(
                "econ_calendar", "macro", indicator
            )
            if not rec:
                continue
            m = rec.get("metrics", {}) if isinstance(rec, dict) else {}
            entry: dict[str, Any] = {}
            for k in ("actual", "forecast", "surprise", "previous"):
                if k in m:
                    try:
                        entry[k] = float(m[k])
                    except (ValueError, TypeError):
                        pass
            if "cesi" in m:
                try:
                    entry["cesi"] = float(m["cesi"])
                except (ValueError, TypeError):
                    pass
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
                except (ValueError, TypeError):
                    pass
        for k in ("meeting_date", "target_rate", "current_target", "trade_date"):
            if k in m:
                out[k] = m[k]
        out["_record_timestamp"] = rec.get("timestamp", "")

        # meeting_date 缺失时，查最近 5 条记录中含 meeting_date 的
        if "meeting_date" not in out or not out.get("meeting_date"):
            try:
                conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM records "
                    "WHERE source = 'cme' AND sub_category = 'fedwatch' "
                    "AND metrics LIKE '%meeting_date%' "
                    "ORDER BY timestamp DESC LIMIT 1"
                )
                row = cursor.fetchone()
                conn.close()
                if row:
                    d = dict(row)
                    m2 = d.get("metrics", "{}")
                    if isinstance(m2, str):
                        try:
                            m2 = json.loads(m2)
                        except Exception:
                            m2 = {}
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
            conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM records "
                "WHERE source = 'cme' AND sub_category = 'fomc_calendar' "
                "ORDER BY timestamp ASC"
            )
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                d = dict(row)
                raw = d.get("raw", "{}")
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = {}
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
            conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM records "
                "WHERE source = 'coinmarketcal' AND sub_category = 'tech_upgrade' "
                "ORDER BY timestamp DESC LIMIT 20"
            )
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                d = dict(row)
                m = d.get("metrics", "{}")
                if isinstance(m, str):
                    try:
                        m = json.loads(m)
                    except Exception:
                        m = {}
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
            conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM records "
                "WHERE source = 'congress' AND sub_category = 'congressional_hearing' "
                "ORDER BY timestamp DESC LIMIT 20"
            )
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                d = dict(row)
                m = d.get("metrics", "{}")
                if isinstance(m, str):
                    try:
                        m = json.loads(m)
                    except Exception:
                        m = {}
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
                except (ValueError, TypeError):
                    pass
        return out

    def _query_latest_record_by_source(
        self, source: str, category: str, sub_category: str | None = None
    ) -> dict | None:
        """查询最新 record by source/category/sub_category。"""
        try:
            conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if sub_category:
                cursor.execute(
                    "SELECT * FROM records "
                    "WHERE source = ? AND category = ? AND sub_category = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (source, category, sub_category),
                )
            else:
                cursor.execute(
                    "SELECT * FROM records "
                    "WHERE source = ? AND category = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (source, category),
                )
            row = cursor.fetchone()
            conn.close()
            if row is None:
                return None
            d = dict(row)
            for key in ("metrics", "timeseries"):
                if key in d and isinstance(d[key], str):
                    try:
                        d[key] = json.loads(d[key])
                    except Exception:
                        pass
            return d
        except Exception as e:
            logger.debug("[FO] query_latest_record_by_source fail: %s", e)
            return None
