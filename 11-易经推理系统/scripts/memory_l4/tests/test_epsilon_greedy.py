"""阶段3 RED 测试 — Epsilon-Greedy 探索策略.

Spec: .trae/documents/strengthen-evolution-exploration.md 阶段3

新增方法 (ExplorationPolicy):
  - get_epsilon(case_count) -> float: 返回 epsilon 概率
  - should_explore(case_count, rng_seed=None) -> bool: 是否走随机探索路径

Epsilon 退火策略:
  - 冷启动 (<10):  epsilon = 0.30 (30% 概率随机探索)
  - 早期 (10-30):  epsilon = 0.20
  - 成熟 (30-100): epsilon = 0.10
  - 稳定 (≥100):   epsilon = 0.05 (硬约束下限)

设计原则 (硬约束):
  - 代码驱动, 纯数学计算, 无 LLM 依赖 (HC-2)
  - FAIL-OPEN: 异常输入 → 返回 False, 不抛错
  - 模块化开关: ENABLE_EVOLUTION_EXPLORATION 默认 False, 关断时 should_explore 永远返回 False
  - rng_seed 可注入, 保证测试可复现
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ============================================================
# sys.path 设置: 复用 test_exploration_policy.py 模式
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreamos.evolution.exploration_policy import ExplorationPolicy


class TestEpsilonValues:
    """Epsilon 退火值测试."""

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_get_epsilon_method_exists(self):
        """get_epsilon 方法存在且可调用."""
        policy = ExplorationPolicy()
        assert hasattr(policy, "get_epsilon")
        assert callable(policy.get_epsilon)

    def test_cold_start_high_epsilon(self):
        """case_count=5 → epsilon=0.30 (冷启动高探索概率)."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=5) == 0.30

    def test_zero_cases_high_epsilon(self):
        """case_count=0 → epsilon=0.30."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=0) == 0.30

    def test_early_epsilon(self):
        """case_count=20 → epsilon=0.20."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=20) == 0.20

    def test_mature_epsilon(self):
        """case_count=50 → epsilon=0.10."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=50) == 0.10

    def test_stable_low_epsilon(self):
        """case_count=150 → epsilon=0.05 (稳定期下限)."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=150) == 0.05

    def test_boundary_10_cases(self):
        """case_count=10 → 早期 epsilon=0.20 (边界)."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=10) == 0.20

    def test_boundary_30_cases(self):
        """case_count=30 → 成熟 epsilon=0.10 (边界)."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=30) == 0.10

    def test_boundary_100_cases(self):
        """case_count=100 → 稳定 epsilon=0.05 (边界)."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=100) == 0.05


class TestShouldExplore:
    """should_explore 方法测试."""

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_should_explore_method_exists(self):
        """should_explore 方法存在且可调用."""
        policy = ExplorationPolicy()
        assert hasattr(policy, "should_explore")
        assert callable(policy.should_explore)

    def test_should_explore_returns_bool(self):
        """should_explore 返回值类型是 bool."""
        policy = ExplorationPolicy()
        result = policy.should_explore(case_count=5, rng_seed=42)
        assert isinstance(result, bool)

    def test_should_explore_with_seed_reproducible(self):
        """相同 rng_seed → 相同结果 (可复现)."""
        policy = ExplorationPolicy()
        result1 = policy.should_explore(case_count=5, rng_seed=42)
        result2 = policy.should_explore(case_count=5, rng_seed=42)
        assert result1 == result2

    def test_should_explore_different_seed_may_differ(self):
        """不同 rng_seed → 结果可能不同 (验证不是固定值)."""
        policy = ExplorationPolicy()
        # 跑多个 seed, 确保至少有一个 True 和一个 False (epsilon=0.30)
        results = [
            policy.should_explore(case_count=5, rng_seed=s)
            for s in range(100)
        ]
        assert True in results, "epsilon=0.30 应至少有一次探索"
        assert False in results, "epsilon=0.30 应至少有一次不探索"

    def test_stable_low_epsilon_rarely_explores(self):
        """稳定期 epsilon=0.05, 100 次中探索次数应 < 20."""
        policy = ExplorationPolicy()
        explore_count = sum(
            1 for s in range(100)
            if policy.should_explore(case_count=150, rng_seed=s)
        )
        assert explore_count < 20, f"稳定期探索频率过高: {explore_count}/100"

    def test_cold_start_high_epsilon_often_explores(self):
        """冷启动 epsilon=0.30, 100 次中探索次数应 > 15."""
        policy = ExplorationPolicy()
        explore_count = sum(
            1 for s in range(100)
            if policy.should_explore(case_count=5, rng_seed=s)
        )
        assert explore_count > 15, f"冷启动探索频率过低: {explore_count}/100"


class TestShouldExploreSwitch:
    """模块化开关测试 (ENABLE_EVOLUTION_EXPLORATION).

    开关关断时:
      - get_epsilon 返回 0.0
      - should_explore 永远返回 False
      - 链路字节等价
    """

    def test_switch_off_get_epsilon_zero(self, monkeypatch):
        """开关关断 → get_epsilon=0.0."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=5) == 0.0
        assert policy.get_epsilon(case_count=150) == 0.0

    def test_switch_off_should_explore_false(self, monkeypatch):
        """开关关断 → should_explore 永远 False (字节等价)."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        policy = ExplorationPolicy()
        assert policy.should_explore(case_count=5, rng_seed=42) is False
        assert policy.should_explore(case_count=150, rng_seed=42) is False

    def test_switch_on_cold_start_explores(self, monkeypatch):
        """ENABLE_EVOLUTION_EXPLORATION=1 + case_count=5 → 有时探索."""
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")
        policy = ExplorationPolicy()
        results = [
            policy.should_explore(case_count=5, rng_seed=s)
            for s in range(100)
        ]
        assert True in results


class TestShouldExploreFailOpen:
    """FAIL-OPEN 测试: 异常输入 → 不抛错."""

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_negative_case_count_no_crash(self):
        """case_count=-1 → 不抛错, 返回 bool."""
        policy = ExplorationPolicy()
        result = policy.should_explore(case_count=-1, rng_seed=42)
        assert isinstance(result, bool)

    def test_non_integer_case_count_no_crash(self):
        """case_count='abc' → 不抛错, 返回 bool."""
        policy = ExplorationPolicy()
        result = policy.should_explore(case_count="abc", rng_seed=42)  # type: ignore[arg-type]
        assert isinstance(result, bool)

    def test_none_case_count_no_crash(self):
        """case_count=None → 不抛错, 返回 bool."""
        policy = ExplorationPolicy()
        result = policy.should_explore(case_count=None, rng_seed=42)  # type: ignore[arg-type]
        assert isinstance(result, bool)

    def test_get_epsilon_negative_returns_zero(self):
        """case_count=-1 → get_epsilon=0.0 (FAIL-OPEN)."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count=-1) == 0.0

    def test_get_epsilon_non_integer_returns_zero(self):
        """case_count='abc' → get_epsilon=0.0 (FAIL-OPEN)."""
        policy = ExplorationPolicy()
        assert policy.get_epsilon(case_count="abc") == 0.0  # type: ignore[arg-type]


class TestExplorationProbeThreshold:
    """探索时的 probe_threshold 降低测试.

    探索时 (should_explore=True):
      - probe_threshold 降低到 0.30 (让更多信号通过)
    非探索时:
      - 走正常 get_probe_threshold 路径
    """

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_get_exploration_probe_threshold_method_exists(self):
        """get_exploration_probe_threshold 方法存在."""
        policy = ExplorationPolicy()
        assert hasattr(policy, "get_exploration_probe_threshold")
        assert callable(policy.get_exploration_probe_threshold)

    def test_exploration_probe_threshold_is_040(self):
        """探索时 probe_threshold=0.40 (Spec 缺陷B: 原 0.30 上调)."""
        policy = ExplorationPolicy()
        assert policy.get_exploration_probe_threshold() == 0.40

    def test_exploration_threshold_lower_than_normal(self):
        """探索阈值 0.40 < 正常冷启动阈值 0.50."""
        policy = ExplorationPolicy()
        normal = policy.get_probe_threshold(case_count=5)
        exploration = policy.get_exploration_probe_threshold()
        assert exploration < normal
