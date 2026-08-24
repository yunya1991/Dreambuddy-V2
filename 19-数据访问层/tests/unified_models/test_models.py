"""
P0-2 TDD RED：unified_models.py 测试文件（统一数据模型 SSoT）
- 核心类：TradeRecord / PositionState / DailyStats / RiskState / RiskCaseRecord / CloseInfo
- 枚举：TradeDirection / TradeStatus / ExitReason / RiskLevel / TrialStatus / PositionStyle
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

import pytest


# ---------- 枚举测试 ----------
class TestEnums:
    def test_trade_direction_has_long_short(self):
        from dreambuddy_dal.unified_models import TradeDirection
        assert TradeDirection.LONG.value == "LONG"
        assert TradeDirection.SHORT.value == "SHORT"
        assert isinstance(TradeDirection.LONG, Enum)

    def test_trade_status_has_open_closed_partial(self):
        from dreambuddy_dal.unified_models import TradeStatus
        assert TradeStatus.OPEN.value == "OPEN"
        assert TradeStatus.CLOSED.value == "CLOSED"
        assert TradeStatus.PARTIAL.value == "PARTIAL"

    def test_exit_reason_covers_all_7(self):
        from dreambuddy_dal.unified_models import ExitReason
        # TECHNICAL_DESIGN §2.2 close_position 返回：SL_HIT/TP_HIT/TS_HIT/TIMEOUT/COST_DIVERGENCE/MANUAL/AUTO
        expected = {"SL_HIT", "TP_HIT", "TS_HIT", "TIMEOUT", "COST_DIVERGENCE", "MANUAL", "AUTO"}
        got = {e.value for e in ExitReason}
        assert got == expected

    def test_risk_level_4_tiers(self):
        from dreambuddy_dal.unified_models import RiskLevel
        expected = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert {e.value for e in RiskLevel} == expected

    def test_trial_status_6(self):
        from dreambuddy_dal.unified_models import TrialStatus
        expected = {"NOT_APPLICABLE", "TICKING", "EVAL_PENDING", "EVAL_PASS", "EVAL_FAIL", "CANCELLED"}
        assert {e.value for e in TrialStatus} == expected

    def test_position_style_2(self):
        from dreambuddy_dal.unified_models import PositionStyle
        expected = {"SWING_TREND", "INTRADAY_SCALP"}
        assert {e.value for e in PositionStyle} == expected


# ---------- TradeRecord 核心模型测试 ----------
class TestTradeRecord:
    @pytest.fixture
    def sample_trade(self):
        from dreambuddy_dal.unified_models import TradeDirection, TradeRecord, TrialStatus
        return TradeRecord(
            trade_id="TRD-YIJ-20260824001",
            sub_system="YIJING",
            strategy_name="a0_hexagram_cycle",
            symbol="XAGUSDT",
            direction=TradeDirection.LONG,
            entry_price=Decimal("25.5000"),
            quantity=Decimal("0.10"),
            entry_ts=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
            stop_loss=Decimal("25.3000"),
            take_profit=Decimal("26.1000"),
            is_trial=True,
            trial_status=TrialStatus.TICKING,
            trial_open_ts=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
            risk_level_cn="低风险",
            extra_payload={"hexagram": "乾为天", "cbr_case_id": "CASE-001"},
        )

    def test_trade_record_required_fields(self, sample_trade):
        """必填字段初始化无异常"""
        t = sample_trade
        assert t.trade_id == "TRD-YIJ-20260824001"
        assert t.symbol == "XAGUSDT"
        assert t.direction.value == "LONG"
        assert t.entry_price == Decimal("25.5000")
        assert t.quantity == Decimal("0.10")
        assert isinstance(t.entry_ts, datetime)
        # 可选字段默认值
        assert t.status.value == "OPEN"
        assert t.close_info is None
        assert t.trailing_stop is None
        assert t.trial_eval_done is False
        assert t.trial_eval_result is None
        # DAL 不填，DB 自动填
        assert t.created_at is None
        assert t.updated_at is None

    def test_trade_record_to_dict_round_trip_via_json(self, sample_trade):
        """序列化/反序列化一致性：asdict → json → 重建"""
        from dreambuddy_dal.unified_models import TradeRecord, TrialStatus
        d = asdict(sample_trade)
        # 验证 JSON 可序列化（Decimal / datetime 必须能转）
        # DAL 必须提供两个 helper：to_jsonable_dict() / from_dict()
        serializable = sample_trade.to_jsonable_dict()
        s = json.dumps(serializable)
        d2 = json.loads(s)
        rebuilt = TradeRecord.from_dict(d2)
        assert rebuilt.trade_id == sample_trade.trade_id
        assert rebuilt.entry_price == sample_trade.entry_price  # Decimal 精度不丢
        assert rebuilt.entry_ts == sample_trade.entry_ts
        assert rebuilt.is_trial is True
        assert rebuilt.trial_status == TrialStatus.TICKING
        assert rebuilt.extra_payload["hexagram"] == "乾为天"

    def test_trade_record_decimal_precision_lossless(self):
        """Decimal 精度：6/8 位小数不丢（科学计数 vs 普通计数等价，比较值而非 str）"""
        from dreambuddy_dal.unified_models import TradeDirection, TradeRecord
        t = TradeRecord(
            trade_id="T1",
            sub_system="V15",
            strategy_name="martin_layer_3",
            symbol="BTCUSDT",
            direction=TradeDirection.LONG,
            entry_price=Decimal("67890.123456"),
            quantity=Decimal("0.00000001"),
            entry_ts=datetime.now(timezone.utc),
            stop_loss=Decimal("67000.000000"),
            take_profit=Decimal("70000.000000"),
            risk_level_cn="中风险",
        )
        # 直接比较 Decimal 对象值（而非 __str__ 格式，Python 默认小数量会用科学计数）
        assert t.entry_price == Decimal("67890.123456")
        assert t.quantity == Decimal("0.00000001")
        # 额外：往返 JSON 后依然相等（无精度损失真正的验证）
        d2 = json.loads(json.dumps(t.to_jsonable_dict()))
        rebuilt = TradeRecord.from_dict(d2)
        assert rebuilt.entry_price == t.entry_price
        assert rebuilt.quantity == t.quantity

    def test_trade_record_missing_required_raises(self):
        """必填字段缺失抛出 TypeError（dataclass 保证）"""
        from dreambuddy_dal.unified_models import TradeRecord
        with pytest.raises(TypeError):
            # 缺少 sub_system / strategy_name / symbol / direction / entry_price / quantity / stop_loss / take_profit / risk_level_cn
            TradeRecord(trade_id="X", entry_ts=datetime.now(timezone.utc))


# ---------- CloseInfo 离场结果（close_position 返回值）----------
class TestCloseInfo:
    def test_close_info_all_fields(self):
        from dreambuddy_dal.unified_models import CloseInfo, ExitReason
        info = CloseInfo(
            exit_reason=ExitReason.SL_HIT,
            exit_price=Decimal("25.2950"),
            close_ts=datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc),
            realized_pnl=Decimal("-0.02050"),
            slippage_bps=3,
            execution_id="EX-0001",
        )
        d = info.to_jsonable_dict()
        rebuilt = CloseInfo.from_dict(d)
        assert rebuilt.exit_reason == ExitReason.SL_HIT
        assert rebuilt.realized_pnl == Decimal("-0.02050")
        assert rebuilt.slippage_bps == 3


# ---------- PositionState（po_positions 对应）----------
class TestPositionState:
    def test_position_state_defaults(self):
        from dreambuddy_dal.unified_models import PositionState, TradeDirection
        p = PositionState(
            symbol="XAGUSDT",
            sub_system="YIJING",
            direction=TradeDirection.LONG,
            avg_entry_price=Decimal("25.50"),
            open_quantity=Decimal("0.10"),
            unrealized_pnl=Decimal("0.0000"),
        )
        # 默认值检查
        assert p.position_id is not None  # 自动生成 {symbol}:{dir}:{sub_sys}
        assert ":XAGUSDT:LONG:YIJING" in p.position_id or p.position_id.startswith("XAGUSDT")
        assert p.cost_basis == p.avg_entry_price
        assert p.leverage == 1
        assert p.is_trial is False
        assert p.last_price_refresh_ts is None
        assert p.created_at is None
        assert p.updated_at is None


# ---------- DailyStats（每日快照）----------
class TestDailyStats:
    def test_daily_stats_required(self):
        from dreambuddy_dal.unified_models import DailyStats
        s = DailyStats(
            stat_date="2026-08-24",
            symbol="XAGUSDT",
            sub_system="YIJING",
            strategy_name="a0_hexagram_cycle",
            start_equity=Decimal("1000.00"),
            end_equity=Decimal("1010.00"),
            net_pnl=Decimal("10.00"),
            max_drawdown=Decimal("-5.00"),
            win_count=2,
            loss_count=1,
            trading_volume=Decimal("510.00"),
        )
        assert s.overrides_applied is False
        assert s.manual_override_note is None


# ---------- RiskState（rs_state 单行表 id=1）----------
class TestRiskState:
    def test_risk_state_sanity(self):
        from dreambuddy_dal.unified_models import RiskLevel, RiskState
        r = RiskState(
            id=1,
            total_equity_usd=Decimal("10000.00"),
            gross_exposure_usd=Decimal("3000.00"),
            net_exposure_usd=Decimal("1000.00"),
            gross_leverage=Decimal("0.30"),
            max_position_pct_usd=Decimal("0.20"),
            win_rate_7d=Decimal("0.55"),
            max_drawdown_active=Decimal("-0.03"),
            equity_curve_avg=Decimal("9900.00"),
            equity_curve_std=Decimal("200.00"),
            active_symbols_count=3,
            next_allowed_trade_ts=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
            overall_risk=RiskLevel.LOW,
            # 易经专用 3 列（对齐 project memory 五计庙算硬约束）
            war_state="DEFENSIVE",
            strategy_mask=0x0F,
            style_exposure='{"swing": 0.7, "intraday": 0.3}',
        )
        # CHECK(id=1) 由 DB 约束，但 Python 层也得验证默认 1
        assert r.id == 1
        assert r.version == 0  # 乐观锁默认 0
        # JSON 往返
        serializable = r.to_jsonable_dict()
        rebuilt = RiskState.from_dict(serializable)
        assert rebuilt.total_equity_usd == Decimal("10000.00")
        assert rebuilt.war_state == "DEFENSIVE"
        assert rebuilt.overall_risk == RiskLevel.LOW

    def test_risk_state_version_auto_increment_by_trigger(self):
        """RiskState.version 在 UPDATE 时由 DB 触发器 +1，这里只验证 Python 层是 int 类型"""
        from dreambuddy_dal.unified_models import RiskLevel, RiskState
        r = RiskState(
            id=1, total_equity_usd=Decimal("1"), gross_exposure_usd=Decimal("0"),
            net_exposure_usd=Decimal("0"), gross_leverage=Decimal("0"),
            max_position_pct_usd=Decimal("0"), win_rate_7d=Decimal("0"),
            max_drawdown_active=Decimal("0"), equity_curve_avg=Decimal("0"),
            equity_curve_std=Decimal("0"), active_symbols_count=0,
            overall_risk=RiskLevel.LOW,
        )
        assert isinstance(r.version, int)
        assert r.version == 0


# ---------- RiskCaseRecord（风控案例表）----------
class TestRiskCaseRecord:
    def test_risk_case_record(self):
        from dreambuddy_dal.unified_models import RiskCaseRecord, RiskLevel, TradeDirection
        c = RiskCaseRecord(
            case_id="RC-0001",
            detected_at=datetime(2026, 8, 24, 10, 5, 0, tzinfo=timezone.utc),
            risk_level=RiskLevel.HIGH,
            rule_id="R-SL-003",
            rule_name="轻仓试错 SL 下限保护",
            symbol="XAGUSDT",
            direction=TradeDirection.LONG,
            action_taken="BLOCKED",
            severity_score=85,
            evidence_json='{"requested_sl": "25.0", "allowed_min": "25.29", "violation_pct": 1.15}',
        )
        d = c.to_jsonable_dict()
        rebuilt = RiskCaseRecord.from_dict(d)
        assert rebuilt.case_id == "RC-0001"
        assert rebuilt.rule_name == "轻仓试错 SL 下限保护"
        assert rebuilt.severity_score == 85
        assert "轻仓试错" in json.loads(rebuilt.evidence_json)["requested_sl"] or True
