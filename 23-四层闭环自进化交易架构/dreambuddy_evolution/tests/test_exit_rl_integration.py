"""
离场 RL 闭环集成测试.
验证 ExitRewardCalculator 接入 + ShadowRL train_policy 调用.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestExitRewardCalculator:
    """ExitRewardCalculator 三组件奖励计算器测试"""

    def test_three_components(self):
        """calculate() 返回 R_total/R_trend/R_risk/R_pnl"""
        from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator
        calc = ExitRewardCalculator()
        result = calc.calculate({
            "cs": 0.8,
            "sl_in_range": True,
            "pnl_pct": 0.05,
            "tp_pct_target": 0.06,
            "sl_pct_target": 0.03,
        })
        assert "R_total" in result
        assert "R_trend" in result
        assert "R_risk" in result
        assert "R_pnl" in result
        # cs=0.8 ≥ 0.7 → R_trend=1.0
        assert result["R_trend"] == 1.0
        # sl_in_range=True → R_risk=0.5
        assert result["R_risk"] == 0.5
        # pnl_pct=0.05, tp=0.06 → 0.05/0.06 ≈ 0.8333（中间区域按比例缩放）
        assert result["R_pnl"] == pytest.approx(0.8333, abs=1e-4)
        # R_total = 0.4*1.0 + 0.3*0.5 + 0.3*0.8333 = 0.4+0.15+0.25 = 0.8
        assert result["R_total"] == pytest.approx(0.8, abs=1e-4)

    def test_fail_open_on_exception(self):
        """异常输入 → 全 0 返回"""
        from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator
        calc = ExitRewardCalculator()
        # 传入无法转换的类型
        result = calc.calculate({"cs": "not_a_number"})
        assert result["R_total"] == 0.0
        assert result["R_trend"] == 0.0
        assert result["R_risk"] == 0.0
        assert result["R_pnl"] == 0.0

    def test_weight_constraints(self):
        """权重硬约束: w_trend=0.4, w_risk=0.3, w_pnl=0.3"""
        from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator
        calc = ExitRewardCalculator()
        result = calc.calculate({"cs": 0.5, "pnl_pct": 0.0})
        assert result["w_trend"] == 0.4
        assert result["w_risk"] == 0.3
        assert result["w_pnl"] == 0.3

    def test_negative_cs_low_reward(self):
        """cs ≤ -0.2 → R_trend=-1.0"""
        from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator
        calc = ExitRewardCalculator()
        result = calc.calculate({"cs": -0.3, "pnl_pct": -0.02})
        assert result["R_trend"] == -1.0

    def test_sl_out_of_range_penalty(self):
        """sl_in_range=False → R_risk=-0.5"""
        from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator
        calc = ExitRewardCalculator()
        result = calc.calculate({"cs": 0.5, "sl_in_range": False, "pnl_pct": 0.01})
        assert result["R_risk"] == -0.5


class TestExitShadowRLTrainPolicy:
    """离场 ShadowRL train_policy 调用测试"""

    def test_train_policy_called_after_activation(self):
        """离场 ShadowRL 样本≥阈值 → train_policy 被调用"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        from dreambuddy_evolution.agi_config import set_switch
        set_switch("enable_shadow_rl_phase3", True)
        try:
            tracker = ShadowRLTracker(max_samples=10000)
            tracker.trainer = MagicMock()
            tracker.trainer.MIN_SAMPLES = 2
            # 记录 2 条样本
            tracker.record("BTC", {"upl_ratio": 0.05}, "force_close", 0.3, {})
            tracker.record("BTC", {"upl_ratio": -0.02}, "force_close", -0.1, {})
            # train_policy 应被调用
            tracker.trainer.train_policy.assert_called_once()
            assert tracker.is_phase3_activated()
        finally:
            set_switch("enable_shadow_rl_phase3", True)

    def test_train_policy_crash_fail_open(self):
        """train_policy 崩溃 → FAIL-OPEN，不阻塞"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        from dreambuddy_evolution.agi_config import set_switch
        set_switch("enable_shadow_rl_phase3", True)
        try:
            tracker = ShadowRLTracker(max_samples=10000)
            tracker.trainer = MagicMock()
            tracker.trainer.MIN_SAMPLES = 2
            tracker.trainer.train_policy.side_effect = RuntimeError("PPO崩溃")
            # 不应抛异常
            tracker.record("BTC", {"upl_ratio": 0.05}, "force_close", 0.3, {})
            tracker.record("BTC", {"upl_ratio": 0.05}, "force_close", 0.3, {})
            # 仍标记为已激活
            assert tracker.is_phase3_activated()
        finally:
            set_switch("enable_shadow_rl_phase3", True)

    def test_train_policy_switch_off_skips(self):
        """关闭 enable_shadow_rl_phase3 → train_policy 不被调用"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        from dreambuddy_evolution.agi_config import set_switch
        set_switch("enable_shadow_rl_phase3", False)
        try:
            tracker = ShadowRLTracker(max_samples=10000)
            tracker.trainer = MagicMock()
            tracker.trainer.MIN_SAMPLES = 2
            tracker.record("BTC", {"upl_ratio": 0.05}, "force_close", 0.3, {})
            tracker.record("BTC", {"upl_ratio": 0.05}, "force_close", 0.3, {})
            tracker.trainer.train_policy.assert_not_called()
            assert not tracker.is_phase3_activated()
        finally:
            set_switch("enable_shadow_rl_phase3", True)

    def test_exit_reward_replaces_hardcoded(self):
        """验证 reward 来自 ExitRewardCalculator 而非 upl_ratio*5.0"""
        from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator
        calc = ExitRewardCalculator()
        # 模拟离场场景：cs=0.8, pnl=5%, action=force_close
        result = calc.calculate({
            "cs": 0.8,
            "sl_in_range": True,
            "pnl_pct": 0.05,
            "tp_pct_target": 0.06,
            "sl_pct_target": 0.03,
        })
        # 三组件 reward 应该不等于 upl_ratio * 5.0 = 0.25
        assert result["R_total"] != pytest.approx(0.05 * 5.0, abs=1e-4)
        # 三组件 reward = 0.8
        assert result["R_total"] == pytest.approx(0.8, abs=1e-4)
