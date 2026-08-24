"""T2 验收测试：_interp_cycle_bounds() 插值（T_CB1）

位置: scripts/memory_l4/tests/test_cycle_bounds_interp.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_interp.py -v

对应 Spec §3bis.3 大周期边界推导 + §3bis.9 T_CB1。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2 import morph_cycle_predictor as mcp
from bcrm2.morph_cycle_predictor import MorphCyclePredictor


# ================================================================
# 辅助：构造一个不需要 storage 的 predictor 实例
# ================================================================
def _make_predictor() -> MorphCyclePredictor:
    """构造 MorphCyclePredictor 实例（_interp_cycle_bounds 不依赖 storage）。"""
    # _interp_cycle_bounds 是纯计算方法，不需要 storage 初始化
    # 通过 __new__ 绕过 __init__ 的 storage 依赖
    p = MorphCyclePredictor.__new__(MorphCyclePredictor)
    return p


# ================================================================
# T_CB1: 边界插值正确性
# ================================================================

class TestInterpCycleBoundsBasic:
    """验证 _interp_cycle_bounds 在两锚点间正确插值。"""

    def test_between_anchors_level_interp(self):
        """t_rel=200 在主升浪加速(180)和繁荣过热中段(365)之间，level 按比例插值。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(200.0)

        # alpha = (200 - 180) / (365 - 180) = 20/185 ≈ 0.1081
        alpha = 20.0 / 185.0
        # 主升浪加速: level_range=[0.8, 1.6], level_mean=1.2
        # 繁荣过热中段: level_range=[1.6, 2.8], level_mean=2.2
        exp_lo = 0.8 * (1 - alpha) + 1.6 * alpha
        exp_hi = 1.6 * (1 - alpha) + 2.8 * alpha
        exp_mean = 1.2 * (1 - alpha) + 2.2 * alpha

        assert abs(result["level_lo"] - exp_lo) < 0.01, f"level_lo: {result['level_lo']} vs {exp_lo}"
        assert abs(result["level_hi"] - exp_hi) < 0.01, f"level_hi: {result['level_hi']} vs {exp_hi}"
        assert abs(result["level_mean"] - exp_mean) < 0.01, f"level_mean: {result['level_mean']} vs {exp_mean}"

    def test_between_anchors_phase_hint_nearest(self):
        """t_rel=200 距离 180 更近，phase_hint 取 '主升浪加速' 对应的 '上升'。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(200.0)
        assert result["phase_hint"] == "上升"

    def test_between_anchors_decay_from_phase(self):
        """phase_hint='上升' → decay_strength=0.20。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(200.0)
        assert abs(result["decay_strength"] - 0.20) < 0.001

    def test_between_anchors_amplitude_cap(self):
        """amplitude_cap = (level_hi - level_mean) × CYCLE_BOUNDS_AMPLITUDE_MULT。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(200.0)
        exp_cap = (result["level_hi"] - result["level_mean"]) * mcp.CYCLE_BOUNDS_AMPLITUDE_MULT
        assert abs(result["amplitude_cap"] - exp_cap) < 0.001

    def test_returns_t_rel_current(self):
        """返回结构包含 t_rel_current 字段。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(486.0)
        assert result["t_rel_current"] == 486.0


class TestInterpCycleBoundsEdgeCases:
    """验证边界情况：超出首尾锚点、正好命中锚点。"""

    def test_before_first_anchor_uses_first(self):
        """t_rel=-10 小于第一个锚点(0)，用第一个锚点 '减半复苏' 的 range。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(-10.0)

        # 减半复苏: level_range=[-0.4, 0.4], level_mean=0.0
        assert abs(result["level_lo"] - (-0.4)) < 0.01
        assert abs(result["level_hi"] - 0.4) < 0.01
        assert abs(result["level_mean"] - 0.0) < 0.01
        assert result["phase_hint"] == "蓄力"
        assert abs(result["decay_strength"] - 0.15) < 0.001

    def test_after_last_anchor_uses_last(self):
        """t_rel=2000 大于最后一个锚点(1420)，用最后一个锚点的 range。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(2000.0)

        # 下一轮减半: level_range=[-0.4, 0.4], level_mean=0.0
        assert abs(result["level_lo"] - (-0.4)) < 0.01
        assert abs(result["level_hi"] - 0.4) < 0.01
        assert abs(result["level_mean"] - 0.0) < 0.01
        assert result["phase_hint"] == "蓄力"

    def test_exact_anchor_no_interp(self):
        """t_rel=480 正好命中 '极端狂热顶（见顶）'，无插值。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(480.0)

        # 极端狂热顶: level_range=[3.5, 4.0], level_mean=3.8
        assert abs(result["level_lo"] - 3.5) < 0.001
        assert abs(result["level_hi"] - 4.0) < 0.001
        assert abs(result["level_mean"] - 3.8) < 0.001
        assert result["phase_hint"] == "顶点"
        assert abs(result["decay_strength"] - 0.30) < 0.001

    def test_exact_anchor_peak(self):
        """t_rel=866 正好命中 '恐慌底（见底）'，phase_hint='底点'。"""
        p = _make_predictor()
        result = p._interp_cycle_bounds(866.0)

        assert abs(result["level_lo"] - (-4.0)) < 0.001
        assert abs(result["level_hi"] - (-3.5)) < 0.001
        assert result["phase_hint"] == "底点"
        assert abs(result["decay_strength"] - 0.30) < 0.001


class TestLabelToPhaseHintMapping:
    """验证 label → phase_hint 映射表覆盖所有锚点。"""

    def test_all_anchors_have_phase_hint_mapping(self):
        """CYCLE4Y_PARAM_RANGES 中每个 label 都有对应的 phase_hint 映射。"""
        assert hasattr(mcp, "LABEL_TO_PHASE_HINT")
        mapping = mcp.LABEL_TO_PHASE_HINT
        for rng in mcp.CYCLE4Y_PARAM_RANGES:
            label = rng["label"]
            assert label in mapping, f"label '{label}' 缺少 phase_hint 映射"
            phase = mapping[label]
            assert phase in mcp.CYCLE_BOUNDS_DECAY_BY_PHASE, \
                f"phase_hint '{phase}' 不在 DECAY_BY_PHASE 表中"

    def test_phase_hint_mapping_values(self):
        """验证关键映射：极端狂热顶→顶点，恐慌底→底点，减半复苏→蓄力。"""
        m = mcp.LABEL_TO_PHASE_HINT
        assert m["极端狂热顶（见顶）"] == "顶点"
        assert m["恐慌底（见底）"] == "底点"
        assert m["减半复苏"] == "蓄力"
        assert m["主升浪加速"] == "上升"
