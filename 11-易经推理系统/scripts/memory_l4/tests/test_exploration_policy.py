"""阶段1 RED 测试 — ExplorationPolicy 探索-利用策略管理器.

Spec: .trae/documents/strengthen-evolution-exploration.md 阶段1

新增 1 文件 (纯新增):
  - 1-ARCHITECTURE/dreamos/evolution/exploration_policy.py

设计原则 (硬约束):
  - 代码驱动, 纯数学计算, 无 LLM 依赖 (HC-2)
  - FAIL-OPEN: 异常 → 返回硬编码默认阈值 0.55, 不抛错
  - 模块化开关: ENABLE_EVOLUTION_EXPLORATION 默认 False, 关断时字节等价
  - reward = tanh(pnl_pct/0.02) 归一化 [-1,1] (硬约束, 本文件不涉及计算, 仅阈值)

阈值退火策略:
  - 冷启动 (case_count < 10):   threshold = 0.40 (宽松探索)
  - 早期 (10-30):               threshold = 0.45
  - 成熟 (30-100):              threshold = 0.50
  - 稳定 (>100):                threshold = 0.55 (硬约束值)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ============================================================
# sys.path 设置: 复用 test_washout_w4.py 模式
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreamos.evolution.exploration_policy import ExplorationPolicy


class TestExplorationPolicyThreshold:
    """探索阈值动态调整测试."""

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_cold_start_threshold_below_10_cases(self):
        """case_count=5 → threshold=0.50 (冷启动适度上调, Spec 缺陷B)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=5) == 0.50

    def test_early_threshold_10_to_30_cases(self):
        """case_count=20 → threshold=0.52 (Spec 缺陷B)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=20) == 0.52

    def test_mature_threshold_30_to_100_cases(self):
        """case_count=50 → threshold=0.54 (Spec 缺陷B)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=50) == 0.54

    def test_stable_threshold_above_100_cases(self):
        """case_count=150 → threshold=0.55 (硬约束值, 不变)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=150) == 0.55

    def test_zero_cases_returns_cold_start(self):
        """case_count=0 → threshold=0.50 (冷启动上调)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=0) == 0.50

    def test_boundary_10_cases(self):
        """case_count=10 → 早期 0.52 (边界)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=10) == 0.52

    def test_boundary_30_cases(self):
        """case_count=30 → 成熟 0.54 (边界)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=30) == 0.54

    def test_boundary_100_cases(self):
        """case_count=100 → 稳定 0.55 (边界)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=100) == 0.55


class TestExplorationPolicyMode:
    """探索模式判定测试."""

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_is_cold_start_true_when_below_30(self):
        """case_count=15 → is_cold_start()=True."""
        policy = ExplorationPolicy()
        assert policy.is_cold_start(case_count=15) is True

    def test_is_cold_start_false_when_above_30(self):
        """case_count=35 → is_cold_start()=False."""
        policy = ExplorationPolicy()
        assert policy.is_cold_start(case_count=35) is False

    def test_get_exploration_mode_cold_start(self):
        """case_count=5 → mode='cold_start'."""
        policy = ExplorationPolicy()
        assert policy.get_exploration_mode(case_count=5) == "cold_start"

    def test_get_exploration_mode_early(self):
        """case_count=20 → mode='early'."""
        policy = ExplorationPolicy()
        assert policy.get_exploration_mode(case_count=20) == "early"

    def test_get_exploration_mode_mature(self):
        """case_count=50 → mode='mature'."""
        policy = ExplorationPolicy()
        assert policy.get_exploration_mode(case_count=50) == "mature"

    def test_get_exploration_mode_stable(self):
        """case_count=150 → mode='stable'."""
        policy = ExplorationPolicy()
        assert policy.get_exploration_mode(case_count=150) == "stable"


class TestExplorationPolicySwitch:
    """模块化开关测试 (ENABLE_EVOLUTION_EXPLORATION).

    开关关断时:
      - get_probe_threshold 返回硬编码 0.55
      - is_cold_start 返回 False
      - get_exploration_mode 返回 'stable'
      - 链路字节等价
    """

    def test_switch_off_returns_hardcoded_threshold(self, monkeypatch):
        """ENABLE_EVOLUTION_EXPLORATION 未设置 → threshold=0.55 (字节等价)."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=0) == 0.55
        assert policy.get_probe_threshold(case_count=50) == 0.55

    def test_switch_off_is_cold_start_false(self, monkeypatch):
        """开关关断 → is_cold_start 永远 False."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        policy = ExplorationPolicy()
        assert policy.is_cold_start(case_count=5) is False

    def test_switch_off_mode_stable(self, monkeypatch):
        """开关关断 → mode 永远 'stable'."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        policy = ExplorationPolicy()
        assert policy.get_exploration_mode(case_count=5) == "stable"

    def test_switch_on_cold_start_threshold(self, monkeypatch):
        """ENABLE_EVOLUTION_EXPLORATION=1 + case_count=5 → threshold=0.50 (Spec 缺陷B)."""
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=5) == 0.50


class TestExplorationPolicyFailOpen:
    """FAIL-OPEN 测试: 异常输入 → 返回硬编码默认 0.55."""

    def test_negative_case_count_returns_default(self):
        """case_count=-1 → threshold=0.55 (FAIL-OPEN)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=-1) == 0.55

    def test_non_integer_case_count_returns_default(self):
        """case_count='abc' → threshold=0.55 (FAIL-OPEN)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count="abc") == 0.55  # type: ignore[arg-type]

    def test_none_case_count_returns_default(self):
        """case_count=None → threshold=0.55 (FAIL-OPEN)."""
        policy = ExplorationPolicy()
        assert policy.get_probe_threshold(case_count=None) == 0.55  # type: ignore[arg-type]


class TestExplorationProbeThresholdRaised:
    """探索门槛上调测试 (Spec 缺陷B).

    get_exploration_probe_threshold() 从 0.30 上调到 0.40
    （epsilon-greedy 探索命中时也提高门槛，避免低质量信号放行）
    """

    def test_exploration_probe_threshold_0_40(self):
        """get_exploration_probe_threshold() → 0.40 (原 0.30)."""
        policy = ExplorationPolicy()
        assert policy.get_exploration_probe_threshold() == 0.40
