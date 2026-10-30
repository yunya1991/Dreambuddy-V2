"""PostgresTradeRepository：PG 实现（C4a 第一批）。

对齐基准：SqliteTradeRepository（sqlite_unified/trade_impl.py）。
- 协议 6 方法 100% 匹配 dreambuddy_dal.protocols.trade_repo.TradeRepository
- 序列化复用 sqlite_unified.trade_impl 的 _trade_to_bind/_trade_from_row（字段级一致）
- SQL 方言差异：占位符 %s；建表 DDL 为 PG 语法（TEXT 主键 + timestamptz）
- Decimal→TEXT、ISO 时间戳、close_info JSON、枚举小写：与 sqlite_unified 完全同口径
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from dreambuddy_dal.protocols.trade_repo import TradeRepository
from dreambuddy_dal.unified_models import (
    CloseInfo,
    DailyStats,
    ExitReason,
    TradeRecord,
    TradeStatus,
)

# 复用 sqlite_unified 的序列化（字段级一致的唯一事实源）
from dreambuddy_dal.implementations.sqlite_unified.trade_impl import (
    _TRADE_INSERT_COLUMNS,
    _TRADE_SELECT_COLUMNS,
    _enum_val,
    _iso_z,
    _trade_from_row,
    _trade_to_bind,
)

from dreambuddy_dal.implementations.postgres.connection import get_pg_connection

# =====================================================================
# PG DDL（幂等建表；列集与 sqlite_unified schema_init + 补列后一致）
# =====================================================================
_DDL_TR_TRADES = """
CREATE TABLE IF NOT EXISTS tr_trades (
    trade_id TEXT PRIMARY KEY,
    sub_system TEXT NOT NULL DEFAULT '',
    strategy_name TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'long',
    entry_price TEXT NOT NULL DEFAULT '0',
    quantity TEXT NOT NULL DEFAULT '0',
    entry_ts TEXT,
    stop_loss TEXT,
    take_profit TEXT,
    risk_level_cn TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    position_style TEXT NOT NULL DEFAULT 'SWING_TREND',
    entry_basis TEXT NOT NULL DEFAULT 'MARKET_ORDER',
    position_side TEXT NOT NULL DEFAULT 'BOTH',
    entry_slippage_bps INTEGER NOT NULL DEFAULT 0,
    entry_execution_id TEXT,
    trailing_stop TEXT,
    close_info_json TEXT,
    notes TEXT,
    cbr_case_id TEXT,
    extra_payload TEXT,
    is_trial INTEGER NOT NULL DEFAULT 0,
    trial_status TEXT NOT NULL DEFAULT 'NOT_APPLICABLE',
    trial_open_ts TEXT,
    trial_eval_ts TEXT,
    trial_eval_done INTEGER NOT NULL DEFAULT 0,
    trial_eval_result TEXT,
    exit_reason TEXT,
    exit_price TEXT,
    exit_ts TEXT,
    realized_pnl TEXT NOT NULL DEFAULT '0',
    pnl_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_DDL_TR_DAILY_STATS = """
CREATE TABLE IF NOT EXISTS tr_daily_stats (
    date TEXT NOT NULL,
    stat_date TEXT,
    symbol TEXT NOT NULL DEFAULT 'ALL',
    sub_system TEXT NOT NULL DEFAULT 'ALL',
    strategy_name TEXT NOT NULL DEFAULT 'ALL',
    starting_equity TEXT,
    ending_equity TEXT,
    total_pnl TEXT,
    max_drawdown DOUBLE PRECISION,
    win_trades INTEGER NOT NULL DEFAULT 0,
    loss_trades INTEGER NOT NULL DEFAULT 0,
    trading_volume TEXT NOT NULL DEFAULT '0',
    overrides_applied INTEGER NOT NULL DEFAULT 0,
    manual_override_note TEXT,
    extra_payload TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class PostgresTradeRepository(TradeRepository):
    def __init__(self, dsn: Optional[str] = None):
        self._dsn = dsn
        self._ensure_schema()

    def _conn(self):
        if self._dsn:
            import psycopg2
            return psycopg2.connect(self._dsn)
        from dreambuddy_dal.implementations.postgres.connection import get_pg_connection
        return get_pg_connection()

    def _ensure_schema(self) -> None:
        """幂等建表 + 索引（PG 语法）。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_DDL_TR_TRADES)
                cur.execute(_DDL_TR_DAILY_STATS)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tr_trades_symbol_time "
                    "ON tr_trades(symbol, entry_ts DESC)"
                )
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_tr_daily_stats_comp_key "
                    "ON tr_daily_stats(stat_date, symbol, sub_system, strategy_name)"
                )

    # ================================================================== add_trade
    def add_trade(self, trade: TradeRecord) -> Optional[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM tr_trades WHERE trade_id=%s", (trade.trade_id,)
                )
                if cur.fetchone():
                    return None
                binds = _trade_to_bind(trade)
                placeholders = ", ".join(["%s"] * len(binds))
                cur.execute(
                    f"INSERT INTO tr_trades ({_TRADE_INSERT_COLUMNS}, created_at, updated_at) "
                    f"VALUES ({placeholders}, now(), now())",
                    binds,
                )
        return trade.trade_id

    # ================================================================== get_trade
    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_TRADE_SELECT_COLUMNS} FROM tr_trades WHERE trade_id=%s",
                    (trade_id,),
                )
                row = cur.fetchone()
        return _trade_from_row(row) if row else None

    # ================================================================== query_trades
    def query_trades(
        self,
        symbol: Optional[str] = None,
        *,
        start_ts: Optional[datetime] = None,
        end_ts: Optional[datetime] = None,
        strategy: Optional[str] = None,
        status: Optional[TradeStatus] = None,
        limit: int = 1000,
    ) -> List[TradeRecord]:
        where: list[str] = []
        args: list[object] = []
        if symbol:
            where.append("symbol = %s")
            args.append(symbol)
        if start_ts:
            where.append("entry_ts >= %s")
            args.append(_iso_z(start_ts))
        if end_ts:
            where.append("entry_ts < %s")
            args.append(_iso_z(end_ts))
        if strategy:
            where.append("strategy_name = %s")
            args.append(strategy)
        if status is not None:
            where.append("status = %s")
            args.append(_enum_val(status, lower=True))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = (
            f"SELECT {_TRADE_SELECT_COLUMNS} FROM tr_trades {where_sql} "
            f"ORDER BY entry_ts DESC LIMIT %s"
        )
        args.append(limit)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
        return [_trade_from_row(r) for r in rows]

    # ================================================================== close_position
    def close_position(
        self,
        trade_id: str,
        exit_reason: ExitReason,
        exit_price: Decimal,
        close_ts: datetime,
        realized_pnl: Decimal,
        *,
        slippage_bps: int = 0,
        execution_id: Optional[str] = None,
    ) -> Optional[CloseInfo]:
        ci = CloseInfo(
            exit_reason=exit_reason,
            exit_price=exit_price,
            close_ts=close_ts,
            realized_pnl=realized_pnl,
            slippage_bps=slippage_bps,
            execution_id=execution_id,
        )
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM tr_trades WHERE trade_id=%s", (trade_id,)
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"close_position 失败：trade_id={trade_id!r} 不存在")
                current = str(row[0])
                if current not in {"open", TradeStatus.OPEN.value}:
                    raise ValueError(
                        f"close_position 失败：trade_id={trade_id!r} 当前 status={current!r}，"
                        f"必须是 'open' 才能关仓（禁止重复关仓）"
                    )
                cur.execute(
                    """
                    UPDATE tr_trades SET
                        status = %s,
                        exit_reason = %s,
                        exit_price = %s,
                        exit_ts = %s,
                        realized_pnl = %s,
                        close_info_json = %s,
                        updated_at = now()
                    WHERE trade_id = %s
                    """,
                    (
                        _enum_val(TradeStatus.CLOSED, lower=True),
                        _enum_val(exit_reason),
                        str(exit_price),
                        _iso_z(close_ts),
                        str(realized_pnl),
                        json.dumps(ci.to_jsonable_dict(), ensure_ascii=False),
                        trade_id,
                    ),
                )
        return ci

    # ================================================================== DailyStats
    def add_or_update_daily_stats(self, stats: DailyStats) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM tr_daily_stats
                    WHERE stat_date=%s AND symbol=%s AND sub_system=%s AND strategy_name=%s
                    """,
                    (stats.stat_date, stats.symbol, stats.sub_system, stats.strategy_name),
                )
                if cur.fetchone():
                    cur.execute(
                        """
                        UPDATE tr_daily_stats SET
                            date = %s,
                            starting_equity = %s, ending_equity = %s,
                            total_pnl = %s, max_drawdown = %s,
                            win_trades = %s, loss_trades = %s, trading_volume = %s,
                            overrides_applied = %s, manual_override_note = %s, extra_payload = %s,
                            computed_at = now()
                        WHERE stat_date=%s AND symbol=%s AND sub_system=%s AND strategy_name=%s
                        """,
                        (
                            stats.stat_date,
                            str(stats.start_equity), str(stats.end_equity),
                            str(stats.net_pnl), float(stats.max_drawdown),
                            int(stats.win_count), int(stats.loss_count),
                            str(stats.trading_volume),
                            int(stats.overrides_applied),
                            stats.manual_override_note,
                            json.dumps(stats.extra_payload, ensure_ascii=False),
                            stats.stat_date, stats.symbol, stats.sub_system, stats.strategy_name,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO tr_daily_stats (
                            date, stat_date, symbol, sub_system, strategy_name,
                            starting_equity, ending_equity,
                            total_pnl, max_drawdown, win_trades, loss_trades, trading_volume,
                            overrides_applied, manual_override_note, extra_payload
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            stats.stat_date, stats.stat_date, stats.symbol, stats.sub_system,
                            stats.strategy_name,
                            str(stats.start_equity), str(stats.end_equity),
                            str(stats.net_pnl), float(stats.max_drawdown),
                            int(stats.win_count), int(stats.loss_count),
                            str(stats.trading_volume),
                            int(stats.overrides_applied),
                            stats.manual_override_note,
                            json.dumps(stats.extra_payload, ensure_ascii=False),
                        ),
                    )
        return True

    def get_daily_stats(
        self,
        symbol: str,
        stat_date: str,
        *,
        sub_system: Optional[str] = None,
        strategy_name: Optional[str] = None,
    ) -> Optional[DailyStats]:
        from decimal import Decimal as _D
        where = ["s.stat_date=%s", "s.symbol=%s"]
        args: list[object] = [stat_date, symbol]
        if sub_system:
            where.append("s.sub_system=%s")
            args.append(sub_system)
        if strategy_name:
            where.append("s.strategy_name=%s")
            args.append(strategy_name)
        sql = f"""
        SELECT
            s.stat_date, s.symbol, s.sub_system, s.strategy_name,
            s.starting_equity, s.ending_equity, s.total_pnl, s.max_drawdown,
            s.win_trades, s.loss_trades,
            COALESCE(s.trading_volume, '0') AS tv,
            s.overrides_applied, s.manual_override_note, s.extra_payload
        FROM tr_daily_stats s
        WHERE {' AND '.join(where)}
        ORDER BY s.stat_date DESC
        LIMIT 1
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                row = cur.fetchone()
        if not row:
            return None
        (sd, sym, subs, sname, seq, eeq, net, mdd, wcnt, lcnt, tv,
         oa, mon, ep_raw) = row
        try:
            ep = json.loads(ep_raw) if ep_raw else {}
        except Exception:
            ep = {}
        return DailyStats(
            stat_date=sd,
            symbol=sym,
            sub_system=subs or "ALL",
            strategy_name=sname or "ALL",
            start_equity=_D(str(seq)) if seq is not None else _D("0"),
            end_equity=_D(str(eeq)) if eeq is not None else _D("0"),
            net_pnl=_D(str(net)) if net is not None else _D("0"),
            max_drawdown=_D(str(mdd)) if mdd is not None else _D("0"),
            win_count=int(wcnt or 0),
            loss_count=int(lcnt or 0),
            trading_volume=_D(str(tv)) if tv is not None else _D("0"),
            overrides_applied=bool(oa),
            manual_override_note=mon,  # type: ignore[arg-type]
            extra_payload=ep,
        )


__all__ = ["PostgresTradeRepository"]
