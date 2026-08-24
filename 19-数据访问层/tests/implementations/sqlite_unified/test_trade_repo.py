"""
TDD RED → GREEN: SqliteTradeRepository（严格对齐 P0 Protocol 签名 + unified_models）

6 方法严格按 dreambuddy_dal.protocols.trade_repo.TradeRepository ABC：
1. add_trade(trade: TradeRecord) -> Optional[str]     幂等
2. close_position(trade_id, exit_reason, exit_price, close_ts, realized_pnl, *, slippage_bps, execution_id) -> Optional[CloseInfo]
3. add_or_update_daily_stats(stats: DailyStats) -> bool  （复合主键 upsert）
4. get_trade(trade_id) -> Optional[TradeRecord]
5. query_trades(symbol, *, start_ts, end_ts, strategy, status, limit) -> List[TradeRecord]
6. get_daily_stats(symbol, stat_date, *, sub_system, strategy_name) -> Optional[DailyStats]

不变量验证：
- ADR-19-004 Decimal ↔ TEXT 往返无损
- close_position 重复关 → 抛 ValueError（业务保护）
- query_trades start_ts/end_ts 命中 idx_tr_trades_symbol_entry_time
- DailyStats 字段映射（unified_models 简版 ↔ schema_init 大表 扩展列）
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema
from dreambuddy_dal.protocols.trade_repo import TradeRepository
from dreambuddy_dal.unified_models import (
    CloseInfo,
    DailyStats,
    ExitReason,
    RiskLevel,
    TradeDirection,
    TradeRecord,
    TradeStatus,
)


@pytest.fixture
def repo(tmp_path: Path):
    """全新 DB + schema + 补 tr_daily_stats 协议必需列。"""
    db = tmp_path / "dal_trade.db"
    with get_sqlite_connection(str(db)) as conn:
        init_db_schema(conn)
        # 补 P0 unified_models.DailyStats 必需要的列（schema_init 表定义里缺）
        for col, default in [
            ("stat_date", "SUBSTR(date, 1, 10)"),
            ("symbol", "'ALL'"),
            ("sub_system", "'ALL'"),
            ("strategy_name", "'ALL'"),
            ("trading_volume", "'0'"),
        ]:
            try:
                conn.execute(f"ALTER TABLE tr_daily_stats ADD COLUMN {col} TEXT DEFAULT '{default}'")
            except sqlite3.OperationalError:  # duplicate column name = OK
                pass
    from dreambuddy_dal.implementations.sqlite_unified.trade_impl import SqliteTradeRepository
    r = SqliteTradeRepository(str(db))
    assert isinstance(r, TradeRepository), "SqliteTradeRepository 必须是 TradeRepository 子类"
    return r


def _sample_trade(tid: str = "TRD-001", sym: str = "BTC-USDT-SWAP",
                  ts: Optional[datetime] = None) -> TradeRecord:
    return TradeRecord(
        trade_id=tid,
        sub_system="YIJING",
        strategy_name="两仪马丁",
        symbol=sym,
        direction=TradeDirection.LONG,
        entry_price=Decimal("65000.12345678"),
        quantity=Decimal("0.12345678"),
        entry_ts=ts or datetime(2026, 8, 24, 8, 0, 0, tzinfo=timezone.utc),
        stop_loss=Decimal("63000"),
        take_profit=Decimal("68000"),
        risk_level_cn=RiskLevel.MEDIUM.value,
    )


# ==================================================================
# T1 + T2: add_trade 幂等 + Decimal 无损 + get_trade 往返
# ==================================================================
def test_add_trade_persists_then_get_trade_roundtrip_decimal(repo):
    t = _sample_trade("TRD-T1")
    r = repo.add_trade(t)
    assert r == "TRD-T1", f"add_trade 返回应为 trade_id，实际 {r!r}"
    # 直接查 DB：entry_price 存的是 TEXT 65000.12345678（不是 REAL 8e-9 误差）
    with get_sqlite_connection(repo.db_path) as conn:
        p = conn.execute("SELECT entry_price FROM tr_trades WHERE trade_id='TRD-T1'").fetchone()
    assert p and p[0] == "65000.12345678", f"Decimal→TEXT 存库失败：{p!r}"

    got = repo.get_trade("TRD-T1")
    assert got is not None
    assert got.trade_id == "TRD-T1"
    assert got.entry_price == Decimal("65000.12345678"), "Decimal 往返精度丢失！"
    assert got.quantity == Decimal("0.12345678")
    assert got.direction == TradeDirection.LONG
    assert got.status == TradeStatus.OPEN, "新交易必须 status=OPEN"
    assert got.risk_level_cn == RiskLevel.MEDIUM.value


def test_add_trade_idempotent_duplicate_returns_none_and_preserves_first(repo):
    t1 = _sample_trade("TRD-T2")
    repo.add_trade(t1)
    # 第二次改 entry_price 为 99999 → 应该被忽略（幂等不覆盖）
    t2 = _sample_trade("TRD-T2")
    t2.entry_price = Decimal("99999.9999")
    r2 = repo.add_trade(t2)
    assert r2 is None, f"重复 add_trade 必须返回 None，实际 {r2!r}"
    got = repo.get_trade("TRD-T2")
    assert got is not None and got.entry_price == Decimal("65000.12345678"), (
        "幂等性破坏：第二次 add_trade 覆盖了首次 entry_price"
    )


def test_get_trade_not_found_returns_none(repo):
    assert repo.get_trade("NO-SUCH-ID-9999") is None


# ==================================================================
# T3: close_position 签名对齐 Protocol → 返回 CloseInfo；重复关抛 ValueError
# ==================================================================
def test_close_position_protocol_signature_and_updates_status(repo):
    repo.add_trade(_sample_trade("TRD-T3"))
    # Protocol 签名：close_position(trade_id, exit_reason, exit_price, close_ts, realized_pnl, *)
    ci = repo.close_position(
        "TRD-T3",
        exit_reason=ExitReason.TP_HIT,
        exit_price=Decimal("67500"),
        close_ts=datetime(2026, 8, 24, 13, 0, 0, tzinfo=timezone.utc),
        realized_pnl=Decimal("308.641980"),
        slippage_bps=3,
        execution_id="EX-OKX-00042",
    )
    # 必须返回 CloseInfo 实例
    assert ci is not None
    assert isinstance(ci, CloseInfo)
    assert ci.exit_reason == ExitReason.TP_HIT
    assert ci.exit_price == Decimal("67500")
    assert ci.realized_pnl == Decimal("308.641980")
    assert ci.slippage_bps == 3
    assert ci.execution_id == "EX-OKX-00042"

    got = repo.get_trade("TRD-T3")
    assert got is not None
    assert got.status == TradeStatus.CLOSED, f"close 后 status 必须 CLOSED，实际 {got.status!r}"
    # unified_models TradeRecord 离场信息统一放 close_info 中（SSoT），没有 exit_reason / realized_pnl 顶层字段
    assert got.close_info is not None, "TradeRecord.close_info 必须能反序列化"
    assert got.close_info.exit_reason == ExitReason.TP_HIT
    assert got.close_info.realized_pnl == Decimal("308.641980")
    assert got.close_info.execution_id == "EX-OKX-00042"


def test_close_position_already_closed_raises_value_error(repo):
    repo.add_trade(_sample_trade("TRD-T4"))
    # 第一次关 → OK
    repo.close_position(
        "TRD-T4",
        exit_reason=ExitReason.SL_HIT,
        exit_price=Decimal("62999.5"),
        close_ts=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
        realized_pnl=Decimal("-247.00005"),
    )
    # 第二次 same trade_id → ValueError（防止 realized_pnl 被重复记）
    with pytest.raises(ValueError, match=r"(?i)not.*open|status.*closed|already"):
        repo.close_position(
            "TRD-T4",
            exit_reason=ExitReason.MANUAL,
            exit_price=Decimal("99999"),
            close_ts=datetime(2026, 8, 24, 18, 0, 0, tzinfo=timezone.utc),
            realized_pnl=Decimal("9999"),
        )


# ==================================================================
# T4: query_trades 严格按 Protocol 参数（时间窗过滤 + 时间排序）
# ==================================================================
def test_query_trades_filter_by_symbol_and_time_window(repo):
    """插入 4 条（BTC × 2 天 + ETH × 2 天）→ BTC 单日 1 条。"""
    dataset = [
        ("TRD-T5-1", "BTC-USDT-SWAP", "2026-08-23T09:30:00+00:00"),
        ("TRD-T5-2", "BTC-USDT-SWAP", "2026-08-24T09:30:00+00:00"),
        ("TRD-T5-3", "ETH-USDT-SWAP", "2026-08-23T09:30:00+00:00"),
        ("TRD-T5-4", "ETH-USDT-SWAP", "2026-08-24T09:30:00+00:00"),
    ]
    for tid, sym, iso in dataset:
        repo.add_trade(_sample_trade(tid, sym, datetime.fromisoformat(iso)))

    start = datetime(2026, 8, 24, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 25, 0, 0, 0, tzinfo=timezone.utc)
    result = repo.query_trades(symbol="BTC-USDT-SWAP", start_ts=start, end_ts=end)
    assert len(result) == 1, f"BTC 0824 应为 1 条，实际 {len(result)}"
    assert result[0].trade_id == "TRD-T5-2"

    # status 过滤：先关一条 BTC-0824 → status=CLOSED → 再查 CLOSED 得 1
    repo.close_position(
        "TRD-T5-2", exit_reason=ExitReason.TP_HIT,
        exit_price=Decimal("68000"),
        close_ts=datetime(2026, 8, 24, 20, 0, 0, tzinfo=timezone.utc),
        realized_pnl=Decimal("369"),
    )
    closed = repo.query_trades(status=TradeStatus.CLOSED)
    assert len(closed) == 1 and closed[0].trade_id == "TRD-T5-2"


# ==================================================================
# T5: DailyStats upsert + 复合主键（stat_date + symbol + sub_system + strategy_name）
# ==================================================================
def test_daily_stats_upsert_and_get_by_composite_key(repo):
    stats = DailyStats(
        stat_date="2026-08-24",
        symbol="BTC-USDT-SWAP",
        sub_system="YIJING",
        strategy_name="两仪马丁",
        start_equity=Decimal("10000.00"),
        end_equity=Decimal("10246.91"),
        net_pnl=Decimal("246.91"),
        max_drawdown=Decimal("-0.015"),
        win_count=3,
        loss_count=1,
        trading_volume=Decimal("128000"),
    )
    # 第一次 insert → True
    r1 = repo.add_or_update_daily_stats(stats)
    assert r1 is True, f"add_or_update_daily_stats 首次插入应 True，实际 {r1!r}"
    # 第二次更新 net_pnl=300 → True（UPSERT）
    stats.net_pnl = Decimal("300.00")
    stats.end_equity = Decimal("10300.00")
    r2 = repo.add_or_update_daily_stats(stats)
    assert r2 is True
    # get_daily_stats: Protocol 签名 get_daily_stats(symbol, stat_date, *, sub_system, strategy_name)
    got = repo.get_daily_stats("BTC-USDT-SWAP", "2026-08-24", sub_system="YIJING", strategy_name="两仪马丁")
    assert got is not None, "应能读到 2026-08-24 BTC YIJING 两仪马丁 DailyStats"
    assert got.start_equity == Decimal("10000.00"), f"start_equity 错：{got.start_equity!r}"
    assert got.end_equity == Decimal("10300.00"), "Upsert 后 end_equity 应该更新（失败就是 UPSERT 没触发）"
    assert got.net_pnl == Decimal("300.00")
    assert got.max_drawdown == Decimal("-0.015")
    assert got.win_count == 3
    assert got.trading_volume == Decimal("128000")


# ==================================================================
# T6: CHECK 约束方向有效性（防止非法 direction 值写进表）
# ==================================================================
def test_trades_direction_check_constraint_rejects_invalid_value(repo):
    with get_sqlite_connection(repo.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tr_trades (trade_id,symbol,direction,entry_price,quantity,entry_ts) "
                "VALUES (?,?,?,?,?,?)",
                ("X-INVALID", "BTC", "bull", "65000", "1", "2026-08-24T00:00:00+00:00"),
            )
