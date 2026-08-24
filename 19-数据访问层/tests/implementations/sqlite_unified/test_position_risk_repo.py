"""
TDD 红-绿-重构：SqlitePositionRepository + SqliteRiskRepository
---------------------------------------------------------------
聚焦 P1-2b 2 个 Repository + 乐观锁不变量：
1. PositionState（净持仓汇总）字段 ↔ po_positions 表 做必要的补列 + 映射，保证 Decimal 精度 & roundtrip
2. PositionRepository 四个方法：upsert_position / get_position / list_positions / refresh_mark_price
3. RiskState（全系统风险快照）字段 ↔ rs_state 单行表 + CHECK(id=1)
4. RiskRepository 乐观锁不变量：update_state(expected_version=N) WHERE version=N → 否则 False

覆盖用例：共 10 个（不重跑 schema_init 已断言过的触发器）
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema
from dreambuddy_dal.unified_models import (
    PositionState,
    RiskCaseRecord,
    RiskLevel,
    RiskState,
    TradeDirection,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db_path():
    """每个测试独立临时 SQLite（WAL 模式+init_schema 已做）。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.db"
        with get_sqlite_connection(str(p)) as conn:
            init_db_schema(conn)
        yield str(p)


@pytest.fixture
def pos_repo(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.position_impl import (
        SqlitePositionRepository,
    )
    return SqlitePositionRepository(db_path)


@pytest.fixture
def risk_repo(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.risk_impl import (
        SqliteRiskRepository,
    )
    return SqliteRiskRepository(db_path)


# ---------------------------------------------------------------------------
# 测试数据工厂
# ---------------------------------------------------------------------------
def _sample_pos(symbol: str = "BTC-USDT-SWAP", sub: str = "YIJING",
                direction: TradeDirection = TradeDirection.LONG) -> PositionState:
    return PositionState(
        symbol=symbol,
        sub_system=sub,
        direction=direction,
        avg_entry_price=Decimal("65000.12345678"),
        open_quantity=Decimal("0.5"),
        unrealized_pnl=Decimal("123.45678901"),
        cost_basis=Decimal("64999.99"),
        leverage=10,
        margin_used=Decimal("3250.00617284"),
        mark_price=Decimal("65247.03703458"),
        liquidation_price=Decimal("60500.0"),
        source_trade_ids='["TRD-A","TRD-B"]',
        extra_payload={"trader": "liangyi", "round": 3},
    )


def _sample_risk_state(version: int = 0) -> RiskState:
    return RiskState(
        id=1,  # 永远 1
        total_equity_usd=Decimal("100000.12345678"),
        gross_exposure_usd=Decimal("50000.00000001"),
        net_exposure_usd=Decimal("20000.99999999"),
        gross_leverage=Decimal("0.5"),
        max_position_pct_usd=Decimal("0.10"),
        win_rate_7d=Decimal("0.68"),
        max_drawdown_active=Decimal("0.0314"),
        equity_curve_avg=Decimal("100000"),
        equity_curve_std=Decimal("1234.56"),
        active_symbols_count=3,
        overall_risk=RiskLevel.LOW,
        war_state="ALLOW",
        strategy_mask=0b1110,
        style_exposure='{"martin":0.6,"breakout":0.4}',
        next_allowed_trade_ts=datetime(2026, 8, 25, 0, 0, 0, tzinfo=timezone.utc),
        active_alert_ids='["ALT-1","ALT-2"]',
        extra_payload={"circuit": "NORMAL", "operator": "liangyi"},
        version=version,  # Python 层忽略；DB 触发器自己维护
    )


# ============================================================
# 1. PositionRepository
# ============================================================
def test_upsert_position_then_get_position_roundtrip_decimal(pos_repo):
    """ADR-19-004：avg_entry_price 65000.12345678 → TEXT → 反序列化后 Decimal 精准一致。"""
    ps = _sample_pos()
    ok = pos_repo.upsert_position(ps)
    assert ok is True, f"upsert_position 返回值应为 True，实际 {ok!r}"

    # 直接查 DB：字段存的 TEXT
    with get_sqlite_connection(pos_repo.db_path) as conn:
        # 因为 PositionState 的列名与 DB 不完全对齐，实现会自动补列 avg_entry_price
        row = conn.execute(
            "SELECT position_id, direction, avg_entry_price, open_quantity, source_trade_ids "
            "FROM po_positions WHERE position_id = ?",
            (ps.position_id,),
        ).fetchone()
    assert row is not None, f"position_id={ps.position_id!r} 没写入 po_positions"
    assert row[0] == ps.position_id
    assert row[1] == "long"  # schema CHECK 小写
    assert row[2] == "65000.12345678", f"Decimal→TEXT 失败 {row[2]!r}"
    assert row[3] == "0.5"

    # get_position 精确查
    got = pos_repo.get_position(symbol="BTC-USDT-SWAP", sub_system="YIJING",
                                direction=TradeDirection.LONG)
    assert got is not None
    assert got.position_id == ps.position_id
    assert got.avg_entry_price == Decimal("65000.12345678"), "Decimal 往返精度丢失！"
    assert got.open_quantity == Decimal("0.5")
    assert got.unrealized_pnl == Decimal("123.45678901")
    assert got.cost_basis == Decimal("64999.99")
    assert got.leverage == 10
    assert got.margin_used == Decimal("3250.00617284")
    assert got.source_trade_ids == '["TRD-A","TRD-B"]'
    assert got.extra_payload == {"trader": "liangyi", "round": 3}


def test_get_position_without_subsystem_multiple_rows_raises_value_error(pos_repo):
    """sub_system=None 且 symbol:dir 有多条持仓 → ValueError。"""
    pos_repo.upsert_position(_sample_pos(sub="YIJING"))
    pos_repo.upsert_position(_sample_pos(sub="V15"))
    with pytest.raises(ValueError):
        pos_repo.get_position(symbol="BTC-USDT-SWAP", direction=TradeDirection.LONG)


def test_list_positions_filters(pos_repo):
    """list_positions 三参数过滤：全部 / 子系统 / symbol 跨子系统。"""
    pos_repo.upsert_position(_sample_pos(symbol="BTC", sub="YIJING"))
    pos_repo.upsert_position(_sample_pos(symbol="BTC", sub="V15", direction=TradeDirection.SHORT))
    pos_repo.upsert_position(_sample_pos(symbol="ETH", sub="YIJING", direction=TradeDirection.LONG))

    all_ = pos_repo.list_positions()
    assert len(all_) == 3

    yijing_only = pos_repo.list_positions(sub_system="YIJING")
    assert {p.symbol for p in yijing_only} == {"BTC", "ETH"}

    btc_only = pos_repo.list_positions(symbol="BTC")
    assert len(btc_only) == 2


def test_refresh_mark_price_lightweight_updates_only_price_fields(pos_repo):
    """refresh_mark_price 轻量更新：只改 mark_price / unrealized_pnl / last_price_refresh_ts，不改 avg_entry_price。"""
    ps = _sample_pos()
    pos_repo.upsert_position(ps)
    before = pos_repo.get_position("BTC-USDT-SWAP", "YIJING", TradeDirection.LONG)
    assert before is not None

    refreshed = pos_repo.refresh_mark_price(
        position_id=ps.position_id,
        mark_price=Decimal("66000.12345678"),
        unrealized_pnl=Decimal("500.00000001"),
        refresh_ts=datetime(2026, 8, 24, 14, 30, 0, tzinfo=timezone.utc),
        liquidation_price=Decimal("60000"),
    )
    assert refreshed is True
    got = pos_repo.get_position("BTC-USDT-SWAP", "YIJING", TradeDirection.LONG)
    assert got is not None
    # 核心：avg_entry_price / open_quantity 没变
    assert got.avg_entry_price == Decimal("65000.12345678")
    assert got.open_quantity == Decimal("0.5")
    # 但 mark_price / unrealized_pnl 刷新了
    assert got.mark_price == Decimal("66000.12345678")
    assert got.unrealized_pnl == Decimal("500.00000001")
    assert got.liquidation_price == Decimal("60000")


# ============================================================
# 2. RiskRepository：乐观锁不变量（核心）
# ============================================================
def test_update_state_version_mismatch_returns_false_concurrency_guard(risk_repo):
    """乐观锁核心不变量：version 不一致 → 返回 False；不写库。"""
    # 初始写入（version=0 插入）→ 读回来拿到 version 是 DB 自动种子的值
    s0 = _sample_risk_state()
    first = risk_repo.update_state(s0, expected_version=None)
    assert first is True, "初始单行 INSERT（无 expected_version 约束）必须 True"

    # 读当前 version（DB 自己维护）
    cur = risk_repo.get_state()
    assert cur is not None
    v_now = cur.version

    # 模拟并发：用"旧 version - 1"去更新 → 必然失败
    bad = risk_repo.update_state(
        RiskState(id=1, total_equity_usd=Decimal("999"), gross_exposure_usd=Decimal("1"),
                  net_exposure_usd=Decimal("0"), gross_leverage=Decimal("0"),
                  max_position_pct_usd=Decimal("0"), win_rate_7d=Decimal("0"),
                  max_drawdown_active=Decimal("0"), equity_curve_avg=Decimal("0"),
                  equity_curve_std=Decimal("0"), active_symbols_count=0,
                  overall_risk=RiskLevel.HIGH),
        expected_version=max(0, v_now - 1),  # ← 过期版本
    )
    assert bad is False, "version 不匹配必须返回 False，让上层重试（乐观锁不变量）"

    # total_equity 未被污染（因为没写成功）
    final = risk_repo.get_state()
    assert final is not None
    assert final.total_equity_usd == Decimal("100000.12345678"), "并发冲突时绝不能写脏数据"
    # version 保持不变（或触发 update+rollback 也不会增加）
    assert final.version == v_now, f"冲突版本期望不变 {v_now}，实际 {final.version}"


def test_update_state_version_match_returns_true_and_bumps_version(risk_repo):
    """乐观锁 happy path：expected_version == 当前 → True + version += 1 + 字段值新。"""
    s0 = _sample_risk_state()
    risk_repo.update_state(s0, expected_version=None)
    cur = risk_repo.get_state()
    assert cur is not None
    v_old = cur.version

    ok = risk_repo.update_state(
        RiskState(
            id=1, total_equity_usd=Decimal("200000"), gross_exposure_usd=Decimal("0"),
            net_exposure_usd=Decimal("0"), gross_leverage=Decimal("0"),
            max_position_pct_usd=Decimal("0"), win_rate_7d=Decimal("0"),
            max_drawdown_active=Decimal("0"), equity_curve_avg=Decimal("0"),
            equity_curve_std=Decimal("0"), active_symbols_count=0,
            overall_risk=RiskLevel.MEDIUM,
        ),
        expected_version=v_old,
    )
    assert ok is True
    got = risk_repo.get_state()
    assert got is not None
    assert got.version == v_old + 1, f"成功 update 必须 version+1，期望 {v_old+1} 实际 {got.version}"
    assert got.total_equity_usd == Decimal("200000")
    assert got.overall_risk == RiskLevel.MEDIUM


def test_risk_state_roundtrip_decimal_and_datetime(risk_repo):
    """RiskState 中 10+ Decimal 和 datetime → TEXT 往返精度校验。"""
    s = _sample_risk_state()
    risk_repo.update_state(s, expected_version=None)

    got = risk_repo.get_state()
    assert got is not None
    # 每一个 Decimal 都要精准
    assert got.total_equity_usd == Decimal("100000.12345678")
    assert got.gross_exposure_usd == Decimal("50000.00000001")
    assert got.net_exposure_usd == Decimal("20000.99999999")
    assert got.gross_leverage == Decimal("0.5")
    assert got.max_position_pct_usd == Decimal("0.10")
    assert got.win_rate_7d == Decimal("0.68")
    assert got.max_drawdown_active == Decimal("0.0314")
    assert got.equity_curve_avg == Decimal("100000")
    assert got.equity_curve_std == Decimal("1234.56")
    # RiskLevel enum（schema CHECK 没小写 → 存原样）
    assert got.overall_risk == RiskLevel.LOW
    # datetime（带 tz）
    assert got.next_allowed_trade_ts is not None
    assert got.next_allowed_trade_ts.year == 2026
    # JSON string 原样
    assert got.active_alert_ids == '["ALT-1","ALT-2"]'
    assert got.style_exposure == '{"martin":0.6,"breakout":0.4}'
    # 五计庙算（易经系统）
    assert got.war_state == "ALLOW"
    assert got.strategy_mask == 0b1110
    # extra_payload
    assert got.extra_payload == {"circuit": "NORMAL", "operator": "liangyi"}


def test_add_case_and_query_cases_filter_by_severity_and_risk_level(risk_repo):
    """rs_cases：add_case 幂等 + query_cases severity ≥ min_severity 过滤 + risk_level 过滤。"""
    c_low = RiskCaseRecord(
        case_id="RSK-20260824-001",
        detected_at=datetime(2026, 8, 24, 9, tzinfo=timezone.utc),
        risk_level=RiskLevel.LOW,
        rule_id="R1",
        rule_name="size_breach",
        action_taken="reject_open",
        severity_score=30,
        symbol="BTC",
        trade_id="TRD-001",
        evidence_json='{"size":"10x"}',
        extra_payload={"algo": "martin"},
    )
    c_high = RiskCaseRecord(
        case_id="RSK-20260824-002",
        detected_at=datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        risk_level=RiskLevel.HIGH,
        rule_id="R2",
        rule_name="circuit_breaker",
        action_taken="close_pos",
        severity_score=95,
        symbol="ETH",
        resolution_notes="强平完成",
        resolved_at=datetime(2026, 8, 24, 10, 1, tzinfo=timezone.utc),
    )
    assert risk_repo.add_case(c_low) is True
    assert risk_repo.add_case(c_high) is True
    # 幂等：重复写 → 返回 False（不重复插入）
    assert risk_repo.add_case(c_low) is False

    # query 无过滤 → 2 条
    all_cases = risk_repo.query_cases()
    assert len(all_cases) == 2

    # severity ≥ 80 → 仅 HIGH
    sevs = risk_repo.query_cases(min_severity=80)
    assert len(sevs) == 1
    assert sevs[0].case_id == "RSK-20260824-002"

    # risk_level=LOW + symbol=BTC → 仅 1 条
    lows = risk_repo.query_cases(risk_level=RiskLevel.LOW, symbol="BTC")
    assert len(lows) == 1
    assert lows[0].risk_level == RiskLevel.LOW
    assert lows[0].severity_score == 30
    assert lows[0].evidence_json == '{"size":"10x"}'
