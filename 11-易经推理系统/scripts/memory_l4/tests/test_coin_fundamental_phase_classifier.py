"""E2: 阶段识别器（PhaseClassifier）测试 — TDD 先红后绿。

验证三阶段闭环方法论（P1预期→P2盈收→P3修复）的识别逻辑：
- classify_phase：基于 E5/E6 信号 + 估值分位 + 事件时间线，输出当前阶段
- 混合规则：事件驱动 + 信号阈值 + 估值分位三因子组合
- FAIL-OPEN：异常/无信号 → 默认 P2（中性）
"""
import pytest
import sys
from pathlib import Path

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_phase_classifier import (
    PhaseClassification,
    classify_phase,
    P1_EXPECTATION,
    P2_REVENUE_EXPANSION,
    P3_VALUATION_RECOVERY,
)


# ---------------------------------------------------------------------------
# P1 预期驱动
# ---------------------------------------------------------------------------

class TestClassifyP1:
    """P1 预期驱动阶段：预期事件 pending + E6 质变强 + 估值低。"""

    def test_classify_p1_on_event_and_e6_high(self):
        """预期事件 pending + E6>0.5 + 估值<30 → P1_EXPECTATION。"""
        result = classify_phase(
            coin="CRCL",
            sub_signals={"supply_shrinkage_intensity": 0.2, "value_capture_delta": 0.8},
            valuation_percentile=20,
            event_timeline=[{"type": "mainnet_launch", "status": "pending"}],
        )
        assert isinstance(result, PhaseClassification)
        assert result.current_phase == P1_EXPECTATION
        assert result.phase_confidence > 0.5
        assert "e6_high_val_low" in result.switch_triggers

    def test_classify_p1_no_event_but_e6_high_val_low(self):
        """无事件但 E6>0.5 + 估值<30 → P1（信号阈值独立触发）。"""
        result = classify_phase(
            coin="XXX",
            sub_signals={"supply_shrinkage_intensity": 0.1, "value_capture_delta": 0.7},
            valuation_percentile=15,
        )
        assert result.current_phase == P1_EXPECTATION


# ---------------------------------------------------------------------------
# P2 盈收扩张
# ---------------------------------------------------------------------------

class TestClassifyP2:
    """P2 盈收扩张阶段：E5 收缩强 + E6 正 + 估值中位。"""

    def test_classify_p2_on_e5_e6_both_high(self):
        """E5>0.5 + E6>0.3 + 估值中位 → P2_REVENUE_EXPANSION。"""
        result = classify_phase(
            coin="UNI",
            sub_signals={"supply_shrinkage_intensity": 0.7, "value_capture_delta": 0.5},
            valuation_percentile=50,
        )
        assert result.current_phase == P2_REVENUE_EXPANSION
        assert result.phase_confidence > 0.5
        assert "e5_high_e6_positive" in result.switch_triggers


# ---------------------------------------------------------------------------
# P3 估值修复
# ---------------------------------------------------------------------------

class TestClassifyP3:
    """P3 估值修复阶段：估值高位 + E5 仍正。"""

    def test_classify_p3_on_valuation_high_percentile(self):
        """估值>80 + E5>0.3 → P3_VALUATION_RECOVERY。"""
        result = classify_phase(
            coin="HYPE",
            sub_signals={"supply_shrinkage_intensity": 0.6, "value_capture_delta": 0.1},
            valuation_percentile=85,
        )
        assert result.current_phase == P3_VALUATION_RECOVERY
        assert result.phase_confidence > 0.5
        assert "valuation_high_e5_positive_bds_pass" in result.switch_triggers


# ---------------------------------------------------------------------------
# 阶段切换
# ---------------------------------------------------------------------------

class TestPhaseSwitch:
    """阶段切换：事件落地触发 P1→P2。"""

    def test_phase_switch_p1_to_p2_on_event_landing(self):
        """事件 pending→landed → P1→P2 转换。"""
        shared_signals = {"supply_shrinkage_intensity": 0.3, "value_capture_delta": 0.7}
        shared_val = 25

        # pending → P1
        result_pending = classify_phase(
            coin="CRCL",
            sub_signals=shared_signals,
            valuation_percentile=shared_val,
            event_timeline=[{"type": "mainnet_launch", "status": "pending"}],
        )
        assert result_pending.current_phase == P1_EXPECTATION

        # landed → P2（事件落地触发切换）
        result_landed = classify_phase(
            coin="CRCL",
            sub_signals=shared_signals,
            valuation_percentile=shared_val,
            event_timeline=[{"type": "mainnet_launch", "status": "landed"}],
        )
        assert result_landed.current_phase == P2_REVENUE_EXPANSION
        assert "event_landed_switch_p1_to_p2" in result_landed.switch_triggers


# ---------------------------------------------------------------------------
# 边界与 FAIL-OPEN
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """边界场景与 FAIL-OPEN。"""

    def test_phase_confidence_low_on_weak_signals(self):
        """信号弱且估值中位 → 无强匹配 → 低 confidence 默认 P2。"""
        result = classify_phase(
            coin="XXX",
            sub_signals={"supply_shrinkage_intensity": 0.1, "value_capture_delta": 0.1},
            valuation_percentile=50,
        )
        assert result.current_phase == P2_REVENUE_EXPANSION  # 默认中性
        assert result.phase_confidence < 0.6  # 低 confidence
        assert "default_neutral" in result.switch_triggers

    def test_failopen_returns_neutral_p2(self):
        """空 sub_signals → 默认 P2（FAIL-OPEN）。"""
        result = classify_phase(
            coin="UNKNOWN",
            sub_signals={},
            valuation_percentile=50,
        )
        assert result.current_phase == P2_REVENUE_EXPANSION
        assert result.phase_confidence < 0.5

    def test_evidence_recorded(self):
        """evidence 字段记录 E5/E6/估值输入。"""
        result = classify_phase(
            coin="UNI",
            sub_signals={"supply_shrinkage_intensity": 0.7, "value_capture_delta": 0.5},
            valuation_percentile=50,
        )
        assert result.evidence["e5"] == 0.7
        assert result.evidence["e6"] == 0.5
        assert result.evidence["valuation_percentile"] == 50
