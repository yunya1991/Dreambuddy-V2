"""Postgres MarketMacroRepository（只读 18 data_center.records）。

背景（2026-11-18）：
- 18 的存储后端已切 PG（`DATA_CENTER_BACKEND=postgres`），采集结果统一写入
  `data_center.records(source, category, sub_category, timestamp, metrics jsonb)`；
- 19 原先只有 sqlite_unified / json_legacy 两个宏观域实现，导致 23 通过 19 读取
  funding/OI 时拿不到 18 的实时数据，FO-2 三维度长期降级；
- 本实现把 records 映射为 19 宏观域协议，供 23 等只读消费。写路径仍由 18 负责，
  因此 upsert_* 一律返回 False（只读后端）。

字段约定（由 18 okx_derivatives 采集器写入）：
- funding_rate_pct / funding_rate_annualized_pct / next_funding_rate_pct
- long_short_ratio / long_account_pct / short_account_pct
- open_interest_btc / open_interest_usd
- taker_buy_vol / taker_sell_vol / taker_buy_sell_ratio
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from dreambuddy_dal.implementations.postgres.connection import get_pg_connection
from dreambuddy_dal.protocols.market_macro_repo import MarketMacroRepository

_DEFAULT_SUB = "okx_derivatives"
_HUNDRED = Decimal("100")


def _to_dt(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_metrics(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


class PostgresMarketMacroRepository(MarketMacroRepository):
    """从 18 的 PG records 表映射宏观域协议（只读）。"""

    def __init__(self, sub_category: str = _DEFAULT_SUB, **_kwargs: Any) -> None:
        self._sub = sub_category or _DEFAULT_SUB

    # ── 基础查询 ──────────────────────────────────────────────────
    def _rows(self, sub_category: str, start_ts: datetime, end_ts: datetime):
        with get_pg_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT sub_category, timestamp, metrics FROM records "
                "WHERE sub_category = %s "
                "AND timestamp::timestamptz >= %s AND timestamp::timestamptz < %s "
                "ORDER BY timestamp::timestamptz ASC",
                (sub_category, start_ts, end_ts),
            )
            return cur.fetchall()

    def _row_latest(self, sub_category: str):
        with get_pg_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT timestamp, metrics FROM records "
                "WHERE sub_category = %s ORDER BY timestamp DESC LIMIT 1",
                (sub_category,),
            )
            return cur.fetchone()

    # ── 5.1 恐惧贪婪 ──────────────────────────────────────────────
    def upsert_fear_greed(self, value: int, value_classification: str, ts: datetime) -> bool:
        return False

    def query_fear_greed_by_time(
        self, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[int, str, datetime]]:
        out: List[Tuple[int, str, datetime]] = []
        for _sub, ts, metrics in self._rows("crypto_fear_greed", start_ts, end_ts):
            m = _parse_metrics(metrics)
            val = m.get("value", m.get("fear_greed", m.get("fear_greed_value")))
            if val is None:
                continue
            out.append(
                (
                    int(val),
                    str(m.get("value_classification") or m.get("classification") or ""),
                    _to_dt(ts),
                )
            )
        return out

    # ── 5.2 资金费率 ──────────────────────────────────────────────
    def upsert_funding_rate(self, symbol: str, funding_rate: Decimal, funding_ts: datetime) -> bool:
        return False

    def query_funding_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, datetime]]:
        out: List[Tuple[str, Decimal, datetime]] = []
        for _sub, ts, metrics in self._rows(self._sub, start_ts, end_ts):
            m = _parse_metrics(metrics)
            pct = m.get("funding_rate_pct")
            if pct is None:
                continue
            out.append((symbol, _dec(pct) / _HUNDRED, _to_dt(ts)))
        return out

    # ── 5.3 持仓量 ────────────────────────────────────────────────
    def upsert_open_interest(
        self,
        symbol: str,
        open_interest: Decimal,
        sum_open_interest_value: Decimal,
        ts: datetime,
    ) -> bool:
        return False

    def query_open_interest_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, datetime]]:
        out: List[Tuple[str, Decimal, Decimal, datetime]] = []
        for _sub, ts, metrics in self._rows(self._sub, start_ts, end_ts):
            m = _parse_metrics(metrics)
            oi = m.get("open_interest_btc", m.get("open_interest_amount"))
            if oi is None:
                continue
            out.append(
                (
                    symbol,
                    _dec(oi),
                    _dec(m.get("open_interest_usd", m.get("open_interest_value"))),
                    _to_dt(ts),
                )
            )
        return out

    # ── 5.4 爆仓（18 未采集，返回空） ────────────────────────────
    def upsert_liquidation(
        self,
        symbol: str,
        order_quantity: Decimal,
        side: str,
        price: Decimal,
        total_quantity: Decimal,
        ts: datetime,
    ) -> bool:
        return False

    def query_liquidation_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, str, Decimal, Decimal, datetime]]:
        return []

    # ── 5.5 多空比 ────────────────────────────────────────────────
    def upsert_long_short_ratio(
        self,
        symbol: str,
        long_account: Decimal,
        short_account: Decimal,
        long_short_ratio: Decimal,
        ts: datetime,
    ) -> bool:
        return False

    def query_long_short_ratio_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, Decimal, datetime]]:
        out: List[Tuple[str, Decimal, Decimal, Decimal, datetime]] = []
        for _sub, ts, metrics in self._rows(self._sub, start_ts, end_ts):
            m = _parse_metrics(metrics)
            ratio = m.get("long_short_ratio")
            if ratio is None:
                continue
            out.append(
                (
                    symbol,
                    _dec(m.get("long_account_pct")) / _HUNDRED,
                    _dec(m.get("short_account_pct")) / _HUNDRED,
                    _dec(ratio),
                    _to_dt(ts),
                )
            )
        return out

    # ── 5.6 Taker 主动买卖量 ─────────────────────────────────────
    def upsert_taker_volume(
        self,
        symbol: str,
        buy_vol: Decimal,
        sell_vol: Decimal,
        buy_sell_volume_diff: Decimal,
        buy_sell_volume_ratio: Decimal,
        ts: datetime,
    ) -> bool:
        return False

    def query_taker_volume_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, Decimal, Decimal, datetime]]:
        out: List[Tuple[str, Decimal, Decimal, Decimal, Decimal, datetime]] = []
        for _sub, ts, metrics in self._rows(self._sub, start_ts, end_ts):
            m = _parse_metrics(metrics)
            buy = m.get("taker_buy_vol")
            sell = m.get("taker_sell_vol")
            if buy is None or sell is None:
                continue
            _buy, _sell = _dec(buy), _dec(sell)
            out.append(
                (
                    symbol,
                    _buy,
                    _sell,
                    _buy - _sell,
                    _dec(m.get("taker_buy_sell_ratio")),
                    _to_dt(ts),
                )
            )
        return out

    # ── 5.7 通用指标 ──────────────────────────────────────────────
    def upsert_metric(
        self,
        source: str,
        sub_category: str,
        metric_name: str,
        metric_value: float,
        ts: datetime,
    ) -> bool:
        return False

    def query_metric_by_time(
        self,
        sub_category: str,
        metric_name: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> List[Tuple[str, str, float, datetime]]:
        out: List[Tuple[str, str, float, datetime]] = []
        with get_pg_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT source, timestamp, metrics FROM records "
                "WHERE sub_category = %s "
                "AND timestamp::timestamptz >= %s AND timestamp::timestamptz < %s "
                "ORDER BY timestamp::timestamptz ASC",
                (sub_category, start_ts, end_ts),
            )
            for source, ts, metrics in cur.fetchall():
                val = _parse_metrics(metrics).get(metric_name)
                if val is None:
                    continue
                try:
                    out.append((str(source), metric_name, float(val), _to_dt(ts)))
                except (TypeError, ValueError):
                    continue
        return out

    def query_latest_metric(
        self, sub_category: str, metric_name: str
    ) -> Optional[Tuple[str, float, datetime]]:
        row = self._row_latest(sub_category)
        if not row:
            return None
        ts, metrics = row
        val = _parse_metrics(metrics).get(metric_name)
        if val is None:
            return None
        try:
            return (metric_name, float(val), _to_dt(ts))
        except (TypeError, ValueError):
            return None


__all__ = ["PostgresMarketMacroRepository"]
