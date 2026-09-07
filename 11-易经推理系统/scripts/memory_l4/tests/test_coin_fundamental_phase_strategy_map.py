"""E3: 阶段匹配策略映射表测试 — TDD 先红后绿。

验证 spec 3.8 节策略映射表：
  - PHASE_STRATEGY_MAP：phase × rank → {信号权重偏移, SL/TP 空间建议, 持仓时间建议}
  - get_strategy_hint(phase, rank) -> Dict：查表返回策略提示
  - 案例锚定：CRCL→P1, UNI→P2, HYPE→P3
  - Shadow 不耦合 BCRM2.0，仅记录策略提示到 JSONL 审计日志

用户最新补充的洞察（必须融入）：
  - 抄新不抄旧：阶段优先级 P1 > P2 > P3（CRCL > UNI > HYPE）
  - 预期落地后短期炒作风险上升，需从 UNI/HYPE 重新评估（on_event_landed_hint）
  - 持续跟踪优质标的（monitor_mode=continuous）
"""
import pytest
import sys
from pathlib import Path

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_phase_classifier import (
    P1_EXPECTATION,
    P2_REVENUE_EXPANSION,
    P3_VALUATION_RECOVERY,
)
from force_vector.coin_fundamental_phase_strategy_map import (
    PHASE_STRATEGY_MAP,
    get_strategy_hint,
    get_priority_weight,
    get_case_anchor,
    get_event_landed_switch_hint,
    NEUTRAL_STRATEGY_HINT,
)


# ---------------------------------------------------------------------------
# 1. 表结构完整性
# ---------------------------------------------------------------------------

class TestPhaseStrategyMapStructure:
    """策略映射表结构校验。"""

    def test_map_covers_all_phases(self):
        """表必须覆盖 P1/P2/P3 三个阶段。"""
        assert P1_EXPECTATION in PHASE_STRATEGY_MAP
        assert P2_REVENUE_EXPANSION in PHASE_STRATEGY_MAP
        assert P3_VALUATION_RECOVERY in PHASE_STRATEGY_MAP

    def test_each_phase_covers_s_a_b_ranks(self):
        """每个阶段必须覆盖 S/A/B 三个评级。"""
        for phase, rank_map in PHASE_STRATEGY_MAP.items():
            assert "S" in rank_map, f"phase={phase} 缺 S"
            assert "A" in rank_map, f"phase={phase} 缺 A"
            assert "B" in rank_map, f"phase={phase} 缺 B"

    def test_each_entry_has_required_fields(self):
        """每条记录必须含 6 个核心字段。"""
        required = {
            "signal_weight_bias",
            "sl_space_hint",
            "tp_space_hint",
            "holding_period_hint",
            "case_anchor",
            "priority_weight",
        }
        for phase, rank_map in PHASE_STRATEGY_MAP.items():
            for rank, hint in rank_map.items():
                missing = required - set(hint.keys())
                assert not missing, f"phase={phase} rank={rank} 缺字段: {missing}"


# ---------------------------------------------------------------------------
# 2. P1 预期阶段策略（CRCL 锚定）
# ---------------------------------------------------------------------------

class TestP1ExpectationStrategy:
    """P1 预期驱动阶段策略 — CRCL 案例。"""

    def test_p1_rank_s_higher_tp_short_holding(self):
        """P1 S级：TP 空间↑（预期溢价）、持仓短（预期落地前撤离）。"""
        hint = get_strategy_hint(P1_EXPECTATION, "S")
        assert hint["tp_space_hint"] == "up"
        assert hint["holding_period_hint"] == "short"
        assert hint["case_anchor"] == "CRCL"

    def test_p1_rank_a_light_position_lower_sl_space(self):
        """P1 A级：轻仓试错、SL 空间↓（预期波动大）。"""
        hint = get_strategy_hint(P1_EXPECTATION, "A")
        assert hint["sl_space_hint"] == "down"
        assert hint["holding_period_hint"] == "short"

    def test_p1_rank_b_skip_no_position(self):
        """P1 B级：不开仓。"""
        hint = get_strategy_hint(P1_EXPECTATION, "B")
        assert hint["sl_space_hint"] == "skip"
        assert hint["tp_space_hint"] == "skip"


# ---------------------------------------------------------------------------
# 3. P2 盈收扩张阶段策略（UNI 锚定）
# ---------------------------------------------------------------------------

class TestP2RevenueExpansionStrategy:
    """P2 盈收扩张阶段策略 — UNI 案例。"""

    def test_p2_rank_s_trend_holding_higher_tp_normal_sl(self):
        """P2 S级：趋势持仓、TP 空间↑、SL 常规。"""
        hint = get_strategy_hint(P2_REVENUE_EXPANSION, "S")
        assert hint["holding_period_hint"] == "trend"
        assert hint["tp_space_hint"] == "up"
        assert hint["sl_space_hint"] == "normal"
        assert hint["case_anchor"] == "UNI"

    def test_p2_rank_a_track_revenue(self):
        """P2 A级：跟踪盈收兑现、趋势轻持。"""
        hint = get_strategy_hint(P2_REVENUE_EXPANSION, "A")
        assert hint["holding_period_hint"] == "trend_light"

    def test_p2_rank_b_observe_only(self):
        """P2 B级：仅观察。"""
        hint = get_strategy_hint(P2_REVENUE_EXPANSION, "B")
        assert hint["holding_period_hint"] == "none"


# ---------------------------------------------------------------------------
# 4. P3 估值修复阶段策略（HYPE 锚定）
# ---------------------------------------------------------------------------

class TestP3ValuationRecoveryStrategy:
    """P3 估值修复阶段策略 — HYPE 案例。"""

    def test_p3_rank_s_lower_sl_space_mid_holding(self):
        """P3 S级：大跌承接、SL 空间↓（修复力强）、持仓中长。"""
        hint = get_strategy_hint(P3_VALUATION_RECOVERY, "S")
        assert hint["sl_space_hint"] == "down"
        assert hint["holding_period_hint"] == "mid_long"
        assert hint["case_anchor"] == "HYPE"

    def test_p3_rank_a_light_position_on_stable_market(self):
        """P3 A级：大盘稳定时轻仓。"""
        hint = get_strategy_hint(P3_VALUATION_RECOVERY, "A")
        assert hint["holding_period_hint"] == "light"


# ---------------------------------------------------------------------------
# 5. 抄新不抄旧：优先级 P1 > P2 > P3（用户最新补充）
# ---------------------------------------------------------------------------

class TestPriorityWeightOrdering:
    """抄新不抄旧：阶段优先级 P1 > P2 > P3。

    用户原话："现阶段 UNI 和 CRCL 机会更大，UNI 和 CRCL 中由于 CRCL 有机会
    预期机会更大，抄新不抄旧"。
    """

    def test_priority_p1_gt_p2_gt_p3(self):
        """P1 优先级权重必须严格大于 P2，P2 严格大于 P3。"""
        p1 = get_priority_weight(P1_EXPECTATION)
        p2 = get_priority_weight(P2_REVENUE_EXPANSION)
        p3 = get_priority_weight(P3_VALUATION_RECOVERY)
        assert p1 > p2 > p3
        assert p1 > 0 and p2 > 0 and p3 > 0

    def test_priority_weight_consistent_in_map(self):
        """映射表内 priority_weight 必须与 get_priority_weight 一致。"""
        for phase, rank_map in PHASE_STRATEGY_MAP.items():
            # 同阶段不同 rank 优先级权重应一致（抄新不抄旧是阶段属性）
            weights = {rank: hint["priority_weight"] for rank, hint in rank_map.items()}
            expected = get_priority_weight(phase)
            for rank, w in weights.items():
                # S/A/B 在 priority_weight 上应一致（阶段属性）
                # B 级可能为 0（不开仓），但 S/A 必须等于阶段优先级
                if rank in ("S", "A"):
                    assert w == expected, (
                        f"phase={phase} rank={rank} priority_weight={w} "
                        f"!=阶段权重{expected}"
                    )


# ---------------------------------------------------------------------------
# 6. 案例锚定
# ---------------------------------------------------------------------------

class TestCaseAnchor:
    """每个阶段的案例锚定 — 用于 CBR 相似度检索。"""

    def test_case_anchor_crcl_for_p1(self):
        assert get_case_anchor(P1_EXPECTATION) == "CRCL"

    def test_case_anchor_uni_for_p2(self):
        assert get_case_anchor(P2_REVENUE_EXPANSION) == "UNI"

    def test_case_anchor_hype_for_p3(self):
        assert get_case_anchor(P3_VALUATION_RECOVERY) == "HYPE"


# ---------------------------------------------------------------------------
# 7. 预期落地后切换提示（用户最新补充）
# ---------------------------------------------------------------------------

class TestEventLandedSwitchHint:
    """预期落地后短期炒作风险上升，需从 UNI/HYPE 重新评估。

    用户原话："一旦预期落地，短期风险较高，则会进入到类似 UNI 的增长模式，
    需要跟踪实际基本盘的盈收是否改善...等估值到达一定阶段，就会出现类似
    HYPE 这类"。
    """

    def test_event_landed_hint_from_p1_to_p2(self):
        """P1 预期落地后，切换提示应指向 P2（盈收跟踪）。"""
        hint = get_event_landed_switch_hint(P1_EXPECTATION)
        assert hint["next_phase"] == P2_REVENUE_EXPANSION
        assert "risk_note" in hint
        assert "revenue_track_required" in hint
        assert hint["revenue_track_required"] is True

    def test_event_landed_hint_from_p2_to_p3(self):
        """P2 估值到高位后，切换提示应指向 P3（估值修复）。"""
        hint = get_event_landed_switch_hint(P2_REVENUE_EXPANSION)
        assert hint["next_phase"] == P3_VALUATION_RECOVERY
        assert "valuation_high_required" in hint

    def test_event_landed_hint_from_p3_terminal(self):
        """P3 是终态，切换提示应表示无下一阶段（或回到 P1 循环）。"""
        hint = get_event_landed_switch_hint(P3_VALUATION_RECOVERY)
        # P3 终态：要么无下一阶段，要么循环回 P1
        assert hint["next_phase"] in (None, P1_EXPECTATION)
        assert "terminal" in hint.get("note", "").lower() or hint["next_phase"] is None or hint["next_phase"] == P1_EXPECTATION


# ---------------------------------------------------------------------------
# 8. 容错与边界
# ---------------------------------------------------------------------------

class TestRobustnessAndFailOpen:
    """异常输入的 FAIL-OPEN 行为。"""

    def test_unknown_phase_returns_neutral_strategy(self):
        """未知 phase 返回中性策略（不抛异常）。"""
        hint = get_strategy_hint("UNKNOWN_PHASE", "S")
        assert hint == NEUTRAL_STRATEGY_HINT

    def test_unknown_rank_returns_neutral_strategy(self):
        """未知 rank 返回中性策略。"""
        hint = get_strategy_hint(P1_EXPECTATION, "X")
        assert hint == NEUTRAL_STRATEGY_HINT

    def test_none_phase_returns_neutral(self):
        """phase=None 返回中性策略。"""
        hint = get_strategy_hint(None, "S")
        assert hint == NEUTRAL_STRATEGY_HINT

    def test_none_rank_returns_neutral(self):
        """rank=None 返回中性策略。"""
        hint = get_strategy_hint(P1_EXPECTATION, None)
        assert hint == NEUTRAL_STRATEGY_HINT

    def test_get_priority_weight_unknown_phase_returns_zero(self):
        """未知阶段优先级权重=0（最低，避免误排序）。"""
        assert get_priority_weight("UNKNOWN") == 0

    def test_get_case_anchor_unknown_phase_returns_empty(self):
        """未知阶段案例锚定返回空字符串。"""
        assert get_case_anchor("UNKNOWN") == ""

    def test_get_event_landed_switch_hint_unknown_phase_returns_neutral(self):
        """未知阶段的落地切换提示返回中性（不切换）。"""
        hint = get_event_landed_switch_hint("UNKNOWN")
        assert hint["next_phase"] is None
        assert hint.get("revenue_track_required") is False


# ---------------------------------------------------------------------------
# 9. Shadow 模式不耦合 BCRM2.0
# ---------------------------------------------------------------------------

class TestShadowModeNoBCRMCoupling:
    """策略提示仅用于审计，不耦合 BCRM2.0 实盘决策。"""

    def test_strategy_hint_is_pure_data_no_callable(self):
        """策略提示必须是纯数据（dict），不含可调用对象。"""
        for phase, rank_map in PHASE_STRATEGY_MAP.items():
            for rank, hint in rank_map.items():
                for key, value in hint.items():
                    assert not callable(value), (
                        f"phase={phase} rank={rank} key={key} 是 callable，"
                        f"违反 Shadow 纯数据原则"
                    )

    def test_neutral_strategy_hint_has_expected_keys(self):
        """中性策略提示必须包含所有核心字段。"""
        required = {
            "signal_weight_bias",
            "sl_space_hint",
            "tp_space_hint",
            "holding_period_hint",
            "case_anchor",
            "priority_weight",
        }
        assert required.issubset(set(NEUTRAL_STRATEGY_HINT.keys()))
        assert NEUTRAL_STRATEGY_HINT["signal_weight_bias"] == 0.0
        assert NEUTRAL_STRATEGY_HINT["priority_weight"] == 0
