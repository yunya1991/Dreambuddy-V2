"""C4a PG 后端契约测试（类型映射、事务语义、分页、daily_stats upsert）。

验收（SPEC-L0 C4a）：PG 后端可读写；与既有后端字段级一致。
字段级一致由共享序列化保证：postgres 复用 sqlite_unified 的
_trade_to_bind/_trade_from_row（Decimal→TEXT、ISO 时间戳、枚举小写、close_info JSON），
本文件对此做源级契约断言 + PG 读写往返字段级比对。

DSN 未配置（DAL_PG_URL/DATABASE_URL//etc/dreambuddy-dal.env 均缺失）时整模块 skip。
测试数据：trade_id 前缀 pg-c4a-contract-、sub_system=c4a_contract，teardown 统一清理。
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DAL_ROOT = os.path.join(REPO_ROOT, "19-数据访问层")
for _p in (REPO_ROOT, DAL_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dreambuddy_dal.di import get_trade_repo
from dreambuddy_dal.unified_models import (CloseInfo, DailyStats, ExitReason,
                                           TradeDirection, TradeRecord)

try:
    _REPO = get_trade_repo(backend="postgres")
except Exception:
    _REPO = None

pytestmark = pytest.mark.skipif(
    _REPO is None, reason="PG DSN 未配置，跳过 C4a 契约测试"
)

_PREFIX = "pg-c4a-contract-" + uuid.uuid4().hex[:8] + "-"
_SUB = "c4a_contract"
_STRATEGY = "pg_contract_test"


def _mk_trade(tid, entry_ts, strategy=_STRATEGY):
    return TradeRecord(
        trade_id=tid, sub_system=_SUB, strategy_name=strategy,
        symbol="BTC-USDT-SWAP", direction=TradeDirection.LONG,
        entry_price=Decimal("50000.00"), quantity=Decimal("0.01"),
        entry_ts=entry_ts, stop_loss=Decimal("49000"), take_profit=Decimal("52000"),
        risk_level_cn="中",
    )


def test_serialization_shared_with_sqlite_unified():
    """字段级一致契约：postgres 与 sqlite_unified 共享同一序列化实现。"""
    from dreambuddy_dal.implementations.postgres import trade_impl as pg
    from dreambuddy_dal.implementations.sqlite_unified import trade_impl as sq
    assert pg._trade_to_bind is sq._trade_to_bind
    assert pg._trade_from_row is sq._trade_from_row


def test_type_mapping_roundtrip():
    """类型映射：Decimal/枚举/时区时间戳读写往返字段级一致。"""
    repo = get_trade_repo(backend="postgres")
    tid = _PREFIX + "type"
    # 共享 _iso_z 序列化为毫秒精度（sqlite_unified 与 postgres 一致），用毫秒对齐值保证往返精确相等
    ts = datetime(2026, 10, 30, 12, 0, 0, 123000, tzinfo=timezone.utc)
    assert repo.add_trade(_mk_trade(tid, ts)) == tid
    g = repo.get_trade(tid)
    assert g is not None
    assert g.trade_id == tid
    assert g.symbol == "BTC-USDT-SWAP"
    assert g.direction is TradeDirection.LONG
    assert g.entry_price == Decimal("50000.00")
    assert g.quantity == Decimal("0.01")
    assert g.stop_loss == Decimal("49000")
    assert g.take_profit == Decimal("52000")
    assert g.entry_ts == ts
    assert g.risk_level_cn == "中"
    assert g.sub_system == _SUB and g.strategy_name == _STRATEGY


def test_add_trade_idempotent():
    """事务语义：重复 add 防重，返回 None。"""
    repo = get_trade_repo(backend="postgres")
    tid = _PREFIX + "idem"
    t = _mk_trade(tid, datetime.now(timezone.utc))
    assert repo.add_trade(t) == tid
    assert repo.add_trade(t) is None


def test_close_position_semantics():
    """事务语义：关仓返回 CloseInfo；重复关仓/关不存在均 ValueError 阻断。"""
    repo = get_trade_repo(backend="postgres")
    tid = _PREFIX + "close"
    repo.add_trade(_mk_trade(tid, datetime.now(timezone.utc)))
    ci = repo.close_position(tid, ExitReason.TP_HIT, Decimal("52000.00"),
                             datetime.now(timezone.utc), Decimal("20.00"))
    assert isinstance(ci, CloseInfo)
    assert ci.realized_pnl == Decimal("20.00")
    assert ci.exit_reason is ExitReason.TP_HIT
    with pytest.raises(ValueError):
        repo.close_position(tid, ExitReason.TP_HIT, Decimal("52000.00"),
                            datetime.now(timezone.utc), Decimal("20.00"))
    with pytest.raises(ValueError):
        repo.close_position(_PREFIX + "missing", ExitReason.MANUAL,
                            Decimal("1"), datetime.now(timezone.utc), Decimal("0"))


def test_query_trades_pagination():
    """分页：limit 生效，entry_ts DESC 排序，strategy 过滤隔离。"""
    repo = get_trade_repo(backend="postgres")
    strategy = _STRATEGY + "_page"
    base = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        repo.add_trade(_mk_trade(_PREFIX + "page%d" % i, base + timedelta(seconds=i),
                                strategy=strategy))
    rows = repo.query_trades(strategy=strategy, limit=3)
    assert len(rows) == 3
    assert all(r.strategy_name == strategy for r in rows)
    ts_list = [r.entry_ts for r in rows]
    assert ts_list == sorted(ts_list, reverse=True)
    assert ts_list[0] == base + timedelta(seconds=4)


def test_daily_stats_upsert():
    """daily_stats：同键 upsert 覆盖，get 取最新值。"""
    repo = get_trade_repo(backend="postgres")
    stat_date = "2026-10-30"
    common = dict(stat_date=stat_date, symbol="BTC-USDT-SWAP", sub_system=_SUB,
                  strategy_name=_STRATEGY, start_equity=Decimal("1000"),
                  max_drawdown=Decimal("5"), win_count=1, loss_count=0,
                  trading_volume=Decimal("0.01"))
    ds1 = DailyStats(end_equity=Decimal("1020"), net_pnl=Decimal("20"), **common)
    assert repo.add_or_update_daily_stats(ds1) is True
    ds2 = DailyStats(end_equity=Decimal("1035"), net_pnl=Decimal("35"), **common)
    assert repo.add_or_update_daily_stats(ds2) is True
    gs = repo.get_daily_stats("BTC-USDT-SWAP", stat_date)
    assert gs is not None
    assert gs.net_pnl == Decimal("35")
    assert gs.end_equity == Decimal("1035")


def teardown_module(module):
    """清理本模块测试数据（tr_trades 前缀行 + tr_daily_stats c4a_contract 行）。"""
    if _REPO is None:
        return
    from dreambuddy_dal.implementations.postgres.connection import get_pg_connection
    with get_pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tr_trades WHERE trade_id LIKE %s", (_PREFIX + "%",))
        cur.execute("DELETE FROM tr_daily_stats WHERE sub_system = %s", (_SUB,))
