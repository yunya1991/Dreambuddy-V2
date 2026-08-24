"""
SqliteTradeRepository：SQLite Unified 实现（严格对齐 P0 Protocol 签名 + unified_models SSoT）

不变量：
- TradeRecord / DailyStats / CloseInfo 字段严格按 unified_models.py（P0 已 16 GREEN）
- Protocol 6 方法 100% 匹配 dreambuddy_dal.protocols.trade_repo.TradeRepository
- schema_init 扩展列（strategy_source 等）走 DEFAULT 值，不参与 dataclass 往返
- tr_trades 缺列（position_style / trial_eval_ts 等）由 __init__._ensure_trades_proto_columns() 补
"""
from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone as _tz_utc
from decimal import Decimal
from typing import List, Optional

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.protocols.trade_repo import TradeRepository
from dreambuddy_dal.unified_models import (
    CloseInfo,
    DailyStats,
    ExitReason,
    PositionStyle,
    TradeDirection,
    TradeRecord,
    TradeStatus,
    TrialStatus,
)

# ------------------------------------------------------------------------------
# Column sets：100% 对齐 unified_models.TradeRecord 实际字段
#   SELECT 顺序 = _TRADE_SELECT_COLUMNS
#   INSERT 顺序 = _TRADE_INSERT_COLUMNS （去掉 created_at/updated_at）
# ------------------------------------------------------------------------------
_TRADE_SELECT_COLUMNS = (
    "trade_id, sub_system, strategy_name, symbol, direction, "
    "entry_price, quantity, entry_ts, stop_loss, take_profit, risk_level_cn, "
    "status, position_style, entry_basis, position_side, entry_slippage_bps, entry_execution_id, "
    "trailing_stop, close_info_json, notes, cbr_case_id, extra_payload, "
    "is_trial, trial_status, trial_open_ts, trial_eval_ts, trial_eval_done, trial_eval_result, "
    "exit_reason, exit_price, exit_ts, realized_pnl, pnl_pct, "
    "created_at, updated_at"
)
_TRADE_INSERT_COLUMNS = (
    "trade_id, sub_system, strategy_name, symbol, direction, "
    "entry_price, quantity, entry_ts, stop_loss, take_profit, risk_level_cn, "
    "status, position_style, entry_basis, position_side, entry_slippage_bps, entry_execution_id, "
    "trailing_stop, close_info_json, notes, cbr_case_id, extra_payload, "
    "is_trial, trial_status, trial_open_ts, trial_eval_ts, trial_eval_done, trial_eval_result, "
    "exit_reason, exit_price, exit_ts, realized_pnl, pnl_pct"
)

# schema_init.tr_trades 中缺失但 unified_models.TradeRecord 有（需 ALTER TABLE 补）
_TRADES_MISSING_COLS = [
    ("position_style", "TEXT", "'SWING_TREND'"),
    ("entry_basis", "TEXT", "'MARKET_ORDER'"),
    ("position_side", "TEXT", "'BOTH'"),
    ("entry_slippage_bps", "INTEGER", "0"),
    ("entry_execution_id", "TEXT", "NULL"),
    ("trailing_stop", "TEXT", "NULL"),
    ("notes", "TEXT", "NULL"),
    ("cbr_case_id", "TEXT", "NULL"),
    ("trial_eval_ts", "TEXT", "NULL"),
]


# ===================================================================== helpers
def _iso_z(dt: object) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.astimezone(_tz_utc.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(dt)


def _to_dec(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _enum_val(v, *, lower: bool = False) -> Optional[str]:
    """
    enum → value；lower=True 时再 .lower() 以适配 schema 表级 CHECK 约束。
    - TradeDirection.CHECK('long','short') 小写 → lower=True
    - TradeStatus.CHECK('open','closed','partial') 小写 → lower=True
    - trial_status.CHECK 是 NOT_APPLICABLE 大写字面值 → 保持原值
    """
    if v is None:
        return None
    raw = v.value if hasattr(v, "value") else str(v)
    return str(raw).lower() if lower else str(raw)


def _load_extra_payload(raw) -> dict:
    """JSON 字符串 / dict → dict。None → {}。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw) or {}
        except Exception:
            return {}
    return {}


# =====================================================================
# TradeRecord 行 ↔ dataclass（36 SELECT 列 × 顺序）
# =====================================================================
def _trade_from_row(row) -> TradeRecord:
    (
        trade_id, sub_system, strategy_name, symbol, direction,
        entry_price, quantity, entry_ts, stop_loss, take_profit, risk_level_cn,
        status, position_style, entry_basis, position_side, entry_slippage_bps, entry_execution_id,
        trailing_stop, close_info_json, notes, cbr_case_id, extra_payload_raw,
        is_trial, trial_status, trial_open_ts, trial_eval_ts, trial_eval_done, trial_eval_result,
        exit_reason, exit_price, exit_ts, realized_pnl, pnl_pct,
        _ca, _ua,
    ) = row

    # close_info_json → CloseInfo（ADR-19-004 Decimal→TEXT，用统一 _JsonSerdeMixin）
    close_info: Optional[CloseInfo] = None
    if close_info_json:
        try:
            close_info = CloseInfo.from_dict(json.loads(close_info_json))
        except Exception:
            close_info = None

    # exit_reason 作为枚举优先使用 exit_reason enum 列，否则 fallback 到 close_info 里的值
    exit_reason_e: Optional[ExitReason] = None
    if close_info is not None:
        exit_reason_e = close_info.exit_reason
    elif exit_reason:
        try:
            exit_reason_e = ExitReason(str(exit_reason))
        except ValueError:
            exit_reason_e = None

    # exit_price / exit_ts / realized_pnl 优先用 close_info 的值（一致性保证）
    ex_price = _to_dec(exit_price) if exit_price else Decimal("0")
    ex_ts = (datetime.fromisoformat(str(exit_ts).replace("Z", "+00:00")) if exit_ts else None)
    rpnl = _to_dec(realized_pnl)
    if close_info is not None:
        ex_price = close_info.exit_price
        ex_ts = close_info.close_ts
        rpnl = close_info.realized_pnl

    # 枚举反序列化（小写存储兼容 schema CHECK；再恢复大写 TradeDirection / TradeStatus）
    def _from_enum(enum_cls, raw, default, *, case_insensitive: bool = False):
        if raw is None:
            return default
        raw_str = str(raw)
        try:
            return enum_cls(raw_str)
        except ValueError:
            if case_insensitive:
                for e in enum_cls:
                    if e.value.lower() == raw_str.lower():
                        return e
            return default

    return TradeRecord(
        trade_id=trade_id,
        sub_system=str(sub_system or ""),
        strategy_name=str(strategy_name or ""),
        symbol=str(symbol or ""),
        direction=_from_enum(TradeDirection, direction, TradeDirection.LONG, case_insensitive=True),
        entry_price=_to_dec(entry_price),
        quantity=_to_dec(quantity),
        entry_ts=(datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00")) if entry_ts else None),
        stop_loss=_to_dec(stop_loss) if stop_loss else Decimal("0"),
        take_profit=_to_dec(take_profit) if take_profit else Decimal("0"),
        risk_level_cn=str(risk_level_cn or ""),
        status=_from_enum(TradeStatus, status, TradeStatus.OPEN, case_insensitive=True),
        position_style=_from_enum(PositionStyle, position_style, PositionStyle.SWING_TREND),
        entry_basis=str(entry_basis or "MARKET_ORDER"),
        position_side=str(position_side or "BOTH"),
        entry_slippage_bps=int(entry_slippage_bps or 0),
        entry_execution_id=(entry_execution_id if entry_execution_id is not None else None),
        trailing_stop=_to_dec(trailing_stop) if trailing_stop else None,
        close_info=close_info,
        notes=(notes if notes is not None else None),
        cbr_case_id=(cbr_case_id if cbr_case_id is not None else None),
        extra_payload=_load_extra_payload(extra_payload_raw),
        is_trial=bool(is_trial),
        trial_status=_from_enum(TrialStatus, trial_status, TrialStatus.NOT_APPLICABLE),
        trial_open_ts=(datetime.fromisoformat(str(trial_open_ts).replace("Z", "+00:00")) if trial_open_ts else None),
        trial_eval_ts=(datetime.fromisoformat(str(trial_eval_ts).replace("Z", "+00:00")) if trial_eval_ts else None),
        trial_eval_done=bool(trial_eval_done),
        trial_eval_result=(trial_eval_result if trial_eval_result is not None else None),
    )


def _trade_to_bind(trade: TradeRecord) -> tuple:
    """TradeRecord → INSERT 绑定参数（顺序 = _TRADE_INSERT_COLUMNS 34 项）。"""
    close_json = trade.close_info.to_json() if trade.close_info is not None else None
    # exit_* / realized / pnl_pct 从 close_info 同步（若有）
    if trade.close_info is not None:
        exit_reason_v = _enum_val(trade.close_info.exit_reason)
        exit_price_s = str(trade.close_info.exit_price)
        exit_ts_s = _iso_z(trade.close_info.close_ts)
        rpnl_s = str(trade.close_info.realized_pnl)
    else:
        exit_reason_v = None
        exit_price_s = None
        exit_ts_s = None
        rpnl_s = "0"

    try:
        ep_raw = json.dumps(trade.extra_payload, ensure_ascii=False)
    except Exception:
        ep_raw = json.dumps({}, ensure_ascii=False)

    return (
        trade.trade_id,
        trade.sub_system,
        trade.strategy_name,
        trade.symbol,
        _enum_val(trade.direction, lower=True),
        str(trade.entry_price),
        str(trade.quantity),
        _iso_z(trade.entry_ts),
        str(trade.stop_loss),
        str(trade.take_profit),
        trade.risk_level_cn,
        _enum_val(trade.status, lower=True),
        _enum_val(trade.position_style),
        trade.entry_basis,
        trade.position_side,
        int(trade.entry_slippage_bps or 0),
        trade.entry_execution_id,
        str(trade.trailing_stop) if trade.trailing_stop is not None else None,
        close_json,
        trade.notes,
        trade.cbr_case_id,
        ep_raw,
        int(trade.is_trial),
        _enum_val(trade.trial_status),
        _iso_z(trade.trial_open_ts),
        _iso_z(trade.trial_eval_ts),
        int(trade.trial_eval_done),
        trade.trial_eval_result,
        exit_reason_v,
        exit_price_s,
        exit_ts_s,
        rpnl_s,
        float(trade.pnl_pct or 0.0) if hasattr(trade, "pnl_pct") else 0.0,
    )


# =====================================================================
# SqliteTradeRepository
# =====================================================================
class SqliteTradeRepository(TradeRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_trades_proto_columns()
        self._ensure_daily_stats_proto_columns()

    # ------------------------------------------------------------------ 补列
    def _ensure_trades_proto_columns(self) -> None:
        """schema_init.tr_trades 缺 unified_models.TradeRecord 的 9 列 → ALTER TABLE（幂等）。"""
        with get_sqlite_connection(self.db_path) as conn:
            existing = {c[1] for c in conn.execute("PRAGMA table_info(tr_trades)").fetchall()}
            for col, ty, default in _TRADES_MISSING_COLS:
                if col not in existing:
                    conn.execute(
                        f"ALTER TABLE tr_trades ADD COLUMN {col} {ty} DEFAULT {default}"
                    )

    def _ensure_daily_stats_proto_columns(self) -> None:
        """补 P0 DailyStats 简版列 + 复合唯一索引。"""
        with get_sqlite_connection(self.db_path) as conn:
            existing_cols = {c[1] for c in conn.execute("PRAGMA table_info(tr_daily_stats)").fetchall()}
            add_defs = [
                ("stat_date", "TEXT", "NULL"),
                ("symbol", "TEXT", "'ALL'"),
                ("sub_system", "TEXT", "'ALL'"),
                ("strategy_name", "TEXT", "'ALL'"),
                ("trading_volume", "TEXT", "'0'"),
                ("overrides_applied", "INTEGER", "0"),
                ("manual_override_note", "TEXT", "NULL"),
                ("extra_payload", "TEXT", "NULL"),
            ]
            for col, ty, default in add_defs:
                if col not in existing_cols:
                    conn.execute(
                        f"ALTER TABLE tr_daily_stats ADD COLUMN {col} {ty} DEFAULT {default}"
                    )
            ux_name = "ux_tr_daily_stats_comp_key"
            existing_idx = {r[1] for r in conn.execute("PRAGMA index_list(tr_daily_stats)").fetchall()}
            if ux_name not in existing_idx:
                conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {ux_name} "
                    f"ON tr_daily_stats(stat_date, symbol, sub_system, strategy_name)"
                )

    # ================================================================== add_trade
    def add_trade(self, trade: TradeRecord) -> Optional[str]:
        with get_sqlite_connection(self.db_path) as conn:
            if conn.execute(
                "SELECT 1 FROM tr_trades WHERE trade_id=?", (trade.trade_id,)
            ).fetchone():
                return None
            placeholders = ", ".join(["?"] * len(_trade_to_bind(trade)))
            conn.execute(
                f"INSERT INTO tr_trades ({_TRADE_INSERT_COLUMNS}, created_at, updated_at) "
                f"VALUES ({placeholders}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                _trade_to_bind(trade),
            )
        return trade.trade_id

    # ================================================================== get_trade
    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        with get_sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {_TRADE_SELECT_COLUMNS} FROM tr_trades WHERE trade_id=?",
                (trade_id,),
            ).fetchone()
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
            where.append("symbol = ?")
            args.append(symbol)
        if start_ts:
            where.append("entry_ts >= ?")
            args.append(_iso_z(start_ts))
        if end_ts:
            where.append("entry_ts < ?")
            args.append(_iso_z(end_ts))
        if strategy:
            where.append("strategy_name = ?")
            args.append(strategy)
        if status is not None:
            where.append("status = ?")
            args.append(_enum_val(status, lower=True))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = (
            f"SELECT {_TRADE_SELECT_COLUMNS} FROM tr_trades {where_sql} "
            f"ORDER BY entry_ts DESC LIMIT ?"
        )
        args.append(limit)
        with get_sqlite_connection(self.db_path) as conn:
            rows = conn.execute(sql, args).fetchall()
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
        with get_sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM tr_trades WHERE trade_id=?", (trade_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"close_position 失败：trade_id={trade_id!r} 不存在")
            current = str(row[0])
            if current not in {"open", TradeStatus.OPEN.value}:
                raise ValueError(
                    f"close_position 失败：trade_id={trade_id!r} 当前 status={current!r}，"
                    f"必须是 'open' 才能关仓（禁止重复关仓）"
                )
            conn.execute(
                """
                UPDATE tr_trades SET
                    status = ?,
                    exit_reason = ?,
                    exit_price = ?,
                    exit_ts = ?,
                    realized_pnl = ?,
                    close_info_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE trade_id = ?
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
        with get_sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM tr_daily_stats
                WHERE stat_date=? AND symbol=? AND sub_system=? AND strategy_name=?
                """,
                (stats.stat_date, stats.symbol, stats.sub_system, stats.strategy_name),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE tr_daily_stats SET
                        date = ?,
                        starting_equity = ?, ending_equity = ?,
                        total_pnl = ?, max_drawdown = ?,
                        win_trades = ?, loss_trades = ?, trading_volume = ?,
                        overrides_applied = ?, manual_override_note = ?, extra_payload = ?,
                        computed_at = CURRENT_TIMESTAMP
                    WHERE stat_date=? AND symbol=? AND sub_system=? AND strategy_name=?
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
                conn.execute(
                    """
                    INSERT INTO tr_daily_stats (
                        date, stat_date, symbol, sub_system, strategy_name,
                        starting_equity, ending_equity,
                        total_pnl, max_drawdown, win_trades, loss_trades, trading_volume,
                        overrides_applied, manual_override_note, extra_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        where = ["s.stat_date=?", "s.symbol=?"]
        args: list[object] = [stat_date, symbol]
        if sub_system:
            where.append("s.sub_system=?")
            args.append(sub_system)
        if strategy_name:
            where.append("s.strategy_name=?")
            args.append(strategy_name)
        sql = f"""
        SELECT
            s.stat_date, s.symbol, s.sub_system, s.strategy_name,
            s.starting_equity, s.ending_equity,
            COALESCE(o.total_pnl_override, s.total_pnl) AS net_pnl,
            COALESCE(o.max_drawdown_override, s.max_drawdown) AS mdd,
            s.win_trades, s.loss_trades,
            COALESCE(s.trading_volume, '0') AS tv,
            s.overrides_applied, s.manual_override_note, s.extra_payload
        FROM tr_daily_stats s
        LEFT JOIN tr_daily_stats_overrides o ON s.date = o.date
        WHERE {' AND '.join(where)}
        ORDER BY s.stat_date DESC
        LIMIT 1
        """
        with get_sqlite_connection(self.db_path) as conn:
            row = conn.execute(sql, args).fetchone()
        if not row:
            return None
        (sd, sym, subs, sname, seq, eeq, net, mdd, wcnt, lcnt, tv,
         oa, mon, ep_raw) = row
        return DailyStats(
            stat_date=sd,
            symbol=sym,
            sub_system=subs or "ALL",
            strategy_name=sname or "ALL",
            start_equity=_to_dec(seq),
            end_equity=_to_dec(eeq),
            net_pnl=_to_dec(net),
            max_drawdown=_to_dec(mdd),
            win_count=int(wcnt or 0),
            loss_count=int(lcnt or 0),
            trading_volume=_to_dec(tv),
            overrides_applied=bool(oa),
            manual_override_note=mon,  # type: ignore[arg-type]
            extra_payload=_load_extra_payload(ep_raw),
        )


__all__ = ["SqliteTradeRepository"]
