"""
Phase 1: Shadow RL Phase3 训练器 TDD 测试集
SPEC-AGI升级蓝图.md §4.1.1

验收点：
  - 样本≥2000自动激活（非PR评审）
  - gmax变异：策略基因权重±0.01~0.05随机扰动
  - Thompson sampling：基于Beta(α,β)分布采样策略选择
  - FAIL-OPEN：finrl未安装时降级为record-only，不crash
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from dreambuddy_evolution.core.shadow_rl_trainer import ShadowRLTrainer


# --------------------------------------------------------------------------------
# 1. maybe_activate 自动激活阈值
# --------------------------------------------------------------------------------
class TestMaybeActivate:
    def test_activates_at_2000_samples(self):
        """样本数恰好2000时激活（HC-AGI-01）"""
        trainer = ShadowRLTrainer()
        assert trainer.maybe_activate(sample_count=2000) is True
        assert trainer.is_activated() is True

    def test_activates_above_2000(self):
        trainer = ShadowRLTrainer()
        assert trainer.maybe_activate(sample_count=5000) is True

    def test_not_activated_below_threshold(self):
        """样本<2000时不激活"""
        trainer = ShadowRLTrainer()
        assert trainer.maybe_activate(sample_count=1999) is False
        assert trainer.is_activated() is False

    def test_not_activated_at_zero(self):
        trainer = ShadowRLTrainer()
        assert trainer.maybe_activate(sample_count=0) is False


# --------------------------------------------------------------------------------
# 2. gmax 变异
# --------------------------------------------------------------------------------
class TestMutateGmax:
    def test_mutation_within_range(self):
        """变异幅度在0.01~0.05之间（SPEC §4.1.1）"""
        trainer = ShadowRLTrainer()
        np.random.seed(42)
        original = 0.5
        mutated = trainer.mutate_gmax(original)
        delta = abs(mutated - original)
        assert 0.01 <= delta <= 0.05, f"delta={delta} 超出 [0.01, 0.05]"

    def test_mutation_clamped_to_unit_interval(self):
        """变异后gmax被clamp到[0,1]"""
        trainer = ShadowRLTrainer()
        np.random.seed(0)
        # 接近上界，变异后应被clamp
        mutated_high = trainer.mutate_gmax(0.99)
        assert 0.0 <= mutated_high <= 1.0
        # 接近下界
        mutated_low = trainer.mutate_gmax(0.01)
        assert 0.0 <= mutated_low <= 1.0

    def test_mutation_direction_random(self):
        """变异方向随机（多次调用有正有负）"""
        trainer = ShadowRLTrainer()
        np.random.seed(123)
        directions = set()
        for _ in range(50):
            m = trainer.mutate_gmax(0.5)
            directions.add("up" if m > 0.5 else "down")
        assert "up" in directions and "down" in directions


# --------------------------------------------------------------------------------
# 3. Thompson Sampling
# --------------------------------------------------------------------------------
class TestThompsonSampling:
    def test_returns_float_in_unit_interval(self):
        """Thompson采样返回[0,1]浮点数"""
        trainer = ShadowRLTrainer()
        sample = trainer.thompson_sample(gene_id="G-001", successes=10, failures=5)
        assert isinstance(sample, float)
        assert 0.0 <= sample <= 1.0

    def test_more_successes_higher_expected_value(self):
        """成功率高的基因，Thompson采样期望值更高"""
        trainer = ShadowRLTrainer()
        np.random.seed(42)
        # 高成功率基因
        high_samples = [trainer.thompson_sample("high", successes=90, failures=10) for _ in range(200)]
        # 低成功率基因
        low_samples = [trainer.thompson_sample("low", successes=10, failures=90) for _ in range(200)]
        assert np.mean(high_samples) > np.mean(low_samples)

    def test_beta_parameters_use_pseudocount(self):
        """Beta(α=successes+1, β=failures+1)，即使0成功0失败也可采样"""
        trainer = ShadowRLTrainer()
        np.random.seed(7)
        sample = trainer.thompson_sample("cold", successes=0, failures=0)
        assert 0.0 <= sample <= 1.0
        # Beta(1,1) 是均匀分布，均值约0.5
        samples = [trainer.thompson_sample("cold", successes=0, failures=0) for _ in range(500)]
        assert abs(np.mean(samples) - 0.5) < 0.1

    def test_select_best_gene_by_thompson(self):
        """多基因Thompson采样后选最大值对应的gene_id"""
        trainer = ShadowRLTrainer()
        np.random.seed(99)
        genes = {
            "G-A": (50, 10),   # 高成功率
            "G-B": (10, 50),   # 低成功率
            "G-C": (30, 30),   # 中等
        }
        best = trainer.select_best_gene(genes)
        assert best == "G-A"


# --------------------------------------------------------------------------------
# 4. Beta 参数在线更新
# --------------------------------------------------------------------------------
class TestBetaUpdate:
    def test_update_success_increments_alpha(self):
        """成功反馈增加α"""
        trainer = ShadowRLTrainer()
        trainer.update_beta("G-001", success=True)
        trainer.update_beta("G-001", success=True)
        stats = trainer.get_beta_stats("G-001")
        assert stats["alpha"] == 3  # 1 (pseudo) + 2
        assert stats["beta"] == 1   # 1 (pseudo)

    def test_update_failure_increments_beta(self):
        """失败反馈增加β"""
        trainer = ShadowRLTrainer()
        trainer.update_beta("G-001", success=False)
        stats = trainer.get_beta_stats("G-001")
        assert stats["alpha"] == 1
        assert stats["beta"] == 2

    def test_unknown_gene_returns_default(self):
        stats = ShadowRLTrainer().get_beta_stats("UNKNOWN")
        assert stats == {"alpha": 1, "beta": 1}


# --------------------------------------------------------------------------------
# 5. FAIL-OPEN: finrl 未安装时降级
# --------------------------------------------------------------------------------
class TestFailOpenFinrl:
    def test_train_policy_returns_degraded_when_finrl_missing(self):
        """finrl未安装时train_policy使用内置训练（FAIL-OPEN降级为内置policy gradient）"""
        trainer = ShadowRLTrainer()
        # 模拟 finrl 不可用
        trainer._finrl_available = False
        samples = [{"state": {}, "action": "long", "reward": 1.0}]
        result = trainer.train_policy(samples)
        # finrl 不可用时使用内置训练，status=trained
        assert result["status"] in ("trained", "degraded")
        assert result["samples_seen"] == 1

    def test_train_policy_accepts_samples_list(self):
        """即使降级也接受样本列表输入"""
        trainer = ShadowRLTrainer()
        trainer._finrl_available = False
        result = trainer.train_policy([])
        assert result["status"] == "degraded"


# --------------------------------------------------------------------------------
# 6. 集成: activate + mutate + thompson 闭环
# --------------------------------------------------------------------------------
class TestFullFlow:
    def test_activated_trainer_can_mutate_and_sample(self):
        """激活后的trainer可执行gmax变异+Thompson采样"""
        trainer = ShadowRLTrainer()
        trainer.maybe_activate(2500)
        assert trainer.is_activated()
        # gmax变异
        mutated = trainer.mutate_gmax(0.6)
        assert 0.0 <= mutated <= 1.0
        # Thompson采样
        sample = trainer.thompson_sample("G-001", successes=20, failures=5)
        assert 0.0 <= sample <= 1.0


# --------------------------------------------------------------------------------
# 7. ShadowRLTracker 集成: 自动激活 + trainer 接入
# --------------------------------------------------------------------------------
class TestShadowRLTrackerIntegration:
    def test_tracker_has_trainer(self):
        """ShadowRLTracker内部持有ShadowRLTrainer实例"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        assert hasattr(tracker, "trainer")
        assert isinstance(tracker.trainer, ShadowRLTrainer)

    def test_tracker_not_activated_initially(self):
        """新tracker默认未激活Phase3"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        assert tracker.is_phase3_activated() is False
        assert tracker.trainer.is_activated() is False

    def test_auto_activate_at_2000_samples(self):
        """记录满2000样本时自动激活Phase3（HC-AGI-01）"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        for i in range(1999):
            tracker.record("BTC", {"R_up": 0.5}, "long", 0.01, {"R_up": 0.5})
        assert tracker.is_phase3_activated() is False
        # 第2000条触发自动激活
        tracker.record("BTC", {"R_up": 0.5}, "long", 0.01, {"R_up": 0.5})
        assert tracker.is_phase3_activated() is True
        assert tracker.trainer.is_activated() is True

    def test_manual_activate_phase3(self):
        """手动调用activate_phase3()也能激活trainer"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        tracker.activate_phase3()
        assert tracker.is_phase3_activated() is True
        assert tracker.trainer.is_activated() is True

    def test_mutate_gmax_via_tracker(self):
        """激活后可通过tracker.trainer执行gmax变异"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        tracker.activate_phase3()
        mutated = tracker.trainer.mutate_gmax(0.5)
        assert 0.0 <= mutated <= 1.0
        assert abs(mutated - 0.5) >= 0.01

