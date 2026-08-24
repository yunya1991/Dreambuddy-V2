"""T1 验收测试：大周期弹性边界约束超参（CYCLE_BOUNDS_*）

位置: scripts/memory_l4/tests/test_cycle_bounds_hyperparams.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_hyperparams.py -v

对应 Spec §3bis.4.3 新增超参。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2 import morph_cycle_predictor as mcp


# ================================================================
# T1: CYCLE_BOUNDS_* 超参存在性与默认值
# ================================================================

class TestCycleBoundsHyperparams:
    """验证大周期弹性边界约束的所有超参都已定义且默认值正确。"""

    def test_total_switch_exists_and_defaults_false(self):
        """CYCLE_BOUNDS_ENABLED 总开关默认 False，保持 CLI 字节等价。"""
        assert hasattr(mcp, "CYCLE_BOUNDS_ENABLED")
        assert mcp.CYCLE_BOUNDS_ENABLED is False

    def test_interp_switch_exists_and_defaults_true(self):
        """CYCLE_BOUNDS_INTERP 启用插值边界，默认 True。"""
        assert hasattr(mcp, "CYCLE_BOUNDS_ENABLED")
        assert hasattr(mcp, "CYCLE_BOUNDS_INTERP")
        assert mcp.CYCLE_BOUNDS_INTERP is True

    def test_default_decay_exists(self):
        """CYCLE_BOUNDS_DECAY_DEFAULT 默认 0.20。"""
        assert hasattr(mcp, "CYCLE_BOUNDS_DECAY_DEFAULT")
        assert mcp.CYCLE_BOUNDS_DECAY_DEFAULT == 0.20

    def test_decay_by_phase_table_complete(self):
        """CYCLE_BOUNDS_DECAY_BY_PHASE 包含所有 phase_hint 且值在 [0, 1]。

        必须覆盖 8 个 phase_hint：
        蓄力 / 上升 / 顶部 / 顶点 / 下跌 / 底部 / 底点 / 磨底
        """
        assert hasattr(mcp, "CYCLE_BOUNDS_DECAY_BY_PHASE")
        table = mcp.CYCLE_BOUNDS_DECAY_BY_PHASE
        required = {"蓄力", "上升", "顶部", "顶点", "下跌", "底部", "底点", "磨底"}
        assert set(table.keys()) == required, f"缺少 phase_hint: {required - set(table.keys())}"
        for k, v in table.items():
            assert 0.0 <= v <= 1.0, f"decay {k}={v} 不在 [0, 1]"

    def test_decay_by_phase_extreme_values(self):
        """顶点/底点 decay=0.30（最强回拉），蓄力/磨底 decay=0.15（最弱回拉）。"""
        table = mcp.CYCLE_BOUNDS_DECAY_BY_PHASE
        assert table["顶点"] == 0.30
        assert table["底点"] == 0.30
        assert table["蓄力"] == 0.15
        assert table["磨底"] == 0.15

    def test_amplitude_mult_exists(self):
        """CYCLE_BOUNDS_AMPLITUDE_MULT = 1.5（振幅上限 = (hi - mean) × 此倍数）。"""
        assert hasattr(mcp, "CYCLE_BOUNDS_AMPLITUDE_MULT")
        assert mcp.CYCLE_BOUNDS_AMPLITUDE_MULT == 1.5

    def test_overshoot_trigger_exists(self):
        """CYCLE_BOUNDS_OVERSHOOT_TRIGGER = 5（连续越界 N 天触发锚点大调整）。"""
        assert hasattr(mcp, "CYCLE_BOUNDS_OVERSHOOT_TRIGGER")
        assert mcp.CYCLE_BOUNDS_OVERSHOOT_TRIGGER == 5


class TestCycleBoundsHyperparamsConsistency:
    """验证超参与既有 ANCHOR_* 超参的命名风格一致。"""

    def test_naming_convention_matches_anchor(self):
        """CYCLE_BOUNDS_* 前缀与既有 ANCHOR_* 前缀风格一致。"""
        # 既有大调整超参
        assert hasattr(mcp, "ANCHOR_SWITCH_COOLDOWN_HOURS")
        # 新增边界约束超参前缀应为 CYCLE_BOUNDS_
        for name in ["CYCLE_BOUNDS_ENABLED", "CYCLE_BOUNDS_INTERP",
                     "CYCLE_BOUNDS_DECAY_DEFAULT", "CYCLE_BOUNDS_DECAY_BY_PHASE",
                     "CYCLE_BOUNDS_AMPLITUDE_MULT", "CYCLE_BOUNDS_OVERSHOOT_TRIGGER"]:
            assert hasattr(mcp, name), f"缺少超参: {name}"
