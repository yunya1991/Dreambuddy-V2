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
