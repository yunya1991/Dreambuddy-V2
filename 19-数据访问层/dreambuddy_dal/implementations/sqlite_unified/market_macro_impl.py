"""
SqliteMarketMacroRepository：SQLite Unified 宏观 6 表实现
----------------------------------------------------------
Protocol 字段 ↔ schema_init 真实列 的差异处理（在 __init__ 内 ALTER TABLE 幂等补列）：
| Protocol 参数名              | schema 列名                 | 动作                  |
|------------------------------|----------------------------|----------------------|
| upsert_open_interest: sum_open_interest_value | oi_sum_value (新增)       | _add_column_if_missing |
| upsert_taker_volume: buy_sell_volume_diff    | taker_vol_diff (新增)     | _add_column_if_missing |
| upsert_liquidation: side=BUY/SELL            | liq_short_usdt/liq_long_usdt | 方向映射            |
| mm_long_short_ratio: long_account/short_account | long_accounts/short_accounts | 复数列名映射    |
| 所有 Decimal 参数                           | REAL 列（schema_init 约定）| float(str(d)) 无损转换 |
"""
from __future__ import annotations

from datetime import datetime
from datetime import timezone as _tz_utc
from decimal import Decimal
from typing import List, Tuple

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.protocols.market_macro_repo import MarketMacroRepository


# ===================================================================== helpers
def _to_unix_sec(dt: object) -> int:
    """datetime/int → UNIX 秒。"""
    if isinstance(dt, int):
        return dt
    if isinstance(dt, datetime):
        return int(dt.astimezone(_tz_utc.utc).timestamp())
    try:
        return int(str(dt))
    except Exception as exc:
        raise ValueError(f"无法把 {dt!r} 转成 UNIX 秒整数") from exc


def _from_unix_sec(ts: int) -> datetime:
    """UNIX 秒 → datetime UTC。"""
    return datetime.fromtimestamp(int(ts), tz=_tz_utc.utc)


def _d(v: object) -> float:
    """Decimal/int → float（REAL 列语义）。"""
    if v is None:
        return 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, Decimal):
        return float(str(v))
    if isinstance(v, int):
        return float(v)
    try:
        return float(str(v))
    except Exception:
        return 0.0


def _back_dec(v: object) -> Decimal:
    """Real/int → Decimal（反序列化时保留精度）。"""
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


# ===================================================================== 实现
class SqliteMarketMacroRepository(MarketMacroRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_proto_columns()

    # ------------------------------------------------------------------ 补列
    def _ensure_proto_columns(self) -> None:
        """Protocol 需要但 schema_init 缺列，ALTER TABLE 幂等补。"""
        with get_sqlite_connection(self.db_path) as conn:
            # mm_open_interest 需要 sum_open_interest_value → 补 oi_sum_value REAL
            cols_oi = {c[1] for c in conn.execute("PRAGMA table_info(mm_open_interest)").fetchall()}
            if "oi_sum_value" not in cols_oi:
                conn.execute(
                    "ALTER TABLE mm_open_interest ADD COLUMN oi_sum_value REAL DEFAULT 0"
                )
            # mm_taker_volume 需要 buy_sell_volume_diff → 补 taker_vol_diff REAL
            cols_tv = {c[1] for c in conn.execute("PRAGMA table_info(mm_taker_volume)").fetchall()}
            if "taker_vol_diff" not in cols_tv:
                conn.execute(
                    "ALTER TABLE mm_taker_volume ADD COLUMN taker_vol_diff REAL DEFAULT 0"
                )

    # ================================================================ 5.1 恐惧贪婪
    def upsert_fear_greed(
        self, value: int, value_classification: str, ts: datetime
    ) -> bool:
        unix = _to_unix_sec(ts)
        with get_sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mm_fear_greed
                    (timestamp, fear_greed_index, value_classification)
                VALUES (?, ?, ?)
                """,
                (unix, int(value), str(value_classification)),
            )
        return True

    def query_fear_greed_by_time(
        self, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[int, str, datetime]]:
        s = _to_unix_sec(start_ts)
        e = _to_unix_sec(end_ts)
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT fear_greed_index, value_classification, timestamp
                FROM mm_fear_greed
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (s, e),
            ).fetchall()
        return [
            (int(idx), cls if cls is not None else "", _from_unix_sec(ts))
            for (idx, cls, ts) in rows
        ]

    # ================================================================ 5.2 资金费率
    def upsert_funding_rate(
        self,
        symbol: str,
        funding_rate: Decimal,
        funding_ts: datetime,
    ) -> bool:
        unix = _to_unix_sec(funding_ts)
        with get_sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mm_funding_rate
                    (symbol, timestamp, funding_rate)
                VALUES (?, ?, ?)
                """,
                (str(symbol), unix, _d(funding_rate)),
            )
        return True

    def query_funding_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, datetime]]:
        s = _to_unix_sec(start_ts)
        e = _to_unix_sec(end_ts)
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT symbol, funding_rate, timestamp
                FROM mm_funding_rate
                WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (symbol, s, e),
            ).fetchall()
        return [
            (r[0], _back_dec(r[1]), _from_unix_sec(r[2]))
            for r in rows
        ]

    # ================================================================ 5.3 持仓量
    def upsert_open_interest(
        self, symbol: str, open_interest: Decimal, sum_open_interest_value: Decimal, ts: datetime
    ) -> bool:
        unix = _to_unix_sec(ts)
        with get_sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mm_open_interest
                    (symbol, timestamp, open_interest, oi_sum_value)
                VALUES (?, ?, ?, ?)
                """,
                (symbol, unix, _d(open_interest), _d(sum_open_interest_value)),
            )
        return True

    def query_open_interest_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, datetime]]:
        s = _to_unix_sec(start_ts)
        e = _to_unix_sec(end_ts)
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT symbol, open_interest, COALESCE(oi_sum_value, 0), timestamp
                FROM mm_open_interest
                WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (symbol, s, e),
            ).fetchall()
        return [
            (r[0], _back_dec(r[1]), _back_dec(r[2]), _from_unix_sec(r[3]))
            for r in rows
        ]

    # ================================================================ 5.4 爆仓
    def upsert_liquidation(
        self,
        symbol: str,
        order_quantity: Decimal,
        side: str,  # "BUY" / "SELL"
        price: Decimal,
        total_quantity: Decimal,
        ts: datetime,
    ) -> bool:
        unix = _to_unix_sec(ts)
        side_up = str(side).upper()
        # BUY = 主动买 = 空头爆仓(空平) → 计入 liq_short_usdt
        # SELL = 主动卖 = 多头爆仓(多平) → 计入 liq_long_usdt
        long_usdt = _d(order_quantity) * _d(price) if side_up == "SELL" else 0.0
        short_usdt = _d(order_quantity) * _d(price) if side_up == "BUY" else 0.0
        total_usdt = _d(total_quantity) * _d(price)
        with get_sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mm_liquidation
                    (symbol, timestamp, liq_long_usdt, liq_short_usdt, liq_total_usdt, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (symbol, unix, long_usdt, short_usdt, total_usdt,
                 f'{{"side":"{side_up}","order_qty":{_d(order_quantity)},"price":{_d(price)}}}'),
            )
        return True

    def query_liquidation_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, str, Decimal, Decimal, datetime]]:
        s = _to_unix_sec(start_ts)
        e = _to_unix_sec(end_ts)
        out: list[tuple] = []
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT symbol, liq_long_usdt, liq_short_usdt, liq_total_usdt, timestamp,
                       COALESCE(raw_payload, '{}')
                FROM mm_liquidation
                WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (symbol, s, e),
            ).fetchall()
        for sym, l_usd, s_usd, t_usd, ts, raw in rows:
            import json as _json
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            side = payload.get("side", ("SELL" if float(l_usd or 0) > float(s_usd or 0) else "BUY"))
            p_price = float(payload.get("price", 1.0) or 1.0)
            order_qty = payload.get(
                "order_qty",
                max(float(l_usd or 0), float(s_usd or 0)) / max(p_price, 1e-9),
            )
            price = payload.get("price", p_price)
            total_qty = (
                max(float(l_usd or 0) + float(s_usd or 0), float(t_usd or 0))
                / max(p_price, 1e-9)
            )
            out.append((
                sym,
                _back_dec(order_qty),
                side,
                _back_dec(price),
                _back_dec(total_qty),
                _from_unix_sec(ts),
            ))
        return out

    # ================================================================ 5.5 多空比
    def upsert_long_short_ratio(
        self, symbol: str, long_account: Decimal, short_account: Decimal,
        long_short_ratio: Decimal, ts: datetime,
    ) -> bool:
        unix = _to_unix_sec(ts)
        with get_sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mm_long_short_ratio
                    (symbol, timestamp, long_short_ratio, long_accounts, short_accounts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    symbol, unix, _d(long_short_ratio),
                    int(float(str(long_account))),
                    int(float(str(short_account))),
                ),
            )
        return True

    def query_long_short_ratio_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, Decimal, datetime]]:
        s = _to_unix_sec(start_ts)
        e = _to_unix_sec(end_ts)
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT symbol, long_accounts, short_accounts, long_short_ratio, timestamp
                FROM mm_long_short_ratio
                WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (symbol, s, e),
            ).fetchall()
        return [
            (r[0], _back_dec(r[1]), _back_dec(r[2]), _back_dec(r[3]), _from_unix_sec(r[4]))
            for r in rows
        ]

    # ================================================================ 5.6 Taker 主动买卖量
    def upsert_taker_volume(
        self, symbol: str, buy_vol: Decimal, sell_vol: Decimal,
        buy_sell_volume_diff: Decimal, buy_sell_volume_ratio: Decimal, ts: datetime,
    ) -> bool:
        unix = _to_unix_sec(ts)
        with get_sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mm_taker_volume
                    (symbol, timestamp, taker_buy_vol, taker_sell_vol,
                     taker_vol_diff, taker_buy_sell_ratio)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol, unix,
                    _d(buy_vol), _d(sell_vol),
                    _d(buy_sell_volume_diff), _d(buy_sell_volume_ratio),
                ),
            )
        return True

    def query_taker_volume_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, Decimal, Decimal, datetime]]:
        s = _to_unix_sec(start_ts)
        e = _to_unix_sec(end_ts)
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT symbol, taker_buy_vol, taker_sell_vol,
                       COALESCE(taker_vol_diff, 0), COALESCE(taker_buy_sell_ratio, 0),
                       timestamp
                FROM mm_taker_volume
                WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (symbol, s, e),
            ).fetchall()
        return [
            (r[0], _back_dec(r[1]), _back_dec(r[2]),
             _back_dec(r[3]), _back_dec(r[4]), _from_unix_sec(r[5]))
            for r in rows
        ]


__all__ = ["SqliteMarketMacroRepository"]
