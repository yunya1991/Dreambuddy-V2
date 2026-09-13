"""
Phase 1.2: ESS 适应加速 TDD 测试
SPEC-AGI升级蓝图.md §4.1.2

验收点：
  - 适应步长动态化：CS≥0.9时+0.05，CS∈[0.7,0.9)时+0.02
  - EMA衰减：近期样本权重更高
"""
from __future__ import annotations

import pytest


class TestESSDynamicStep:
    """适应步长动态化：高CS大步长，低CS小步长"""

    def test_high_cs_success_gets_large_step(self):
        """CS≥0.9 且 TP → ess_delta=+0.05（高信心大步长）"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        result = engine.apply_reward(cs=0.95, outcome="TP", cluster_id="c1", ess_id="e1", gmax=0.3)
        assert result["ess_delta"] == pytest.approx(0.05)

    def test_boundary_cs_0_9_gets_large_step(self):
        """CS=0.9 恰好边界 → +0.05"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        result = engine.apply_reward(cs=0.9, outcome="TP", cluster_id="c1", ess_id="e1", gmax=0.3)
        assert result["ess_delta"] == pytest.approx(0.05)

    def test_moderate_cs_success_gets_small_step(self):
        """0.7≤CS<0.9 且 TP → ess_delta=+0.02"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        result = engine.apply_reward(cs=0.8, outcome="TP", cluster_id="c1", ess_id="e1", gmax=0.3)
        assert result["ess_delta"] == pytest.approx(0.02)

    def test_cs_0_7_boundary_gets_small_step(self):
        """CS=0.7 恰好边界 → +0.02"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        result = engine.apply_reward(cs=0.7, outcome="TP", cluster_id="c1", ess_id="e1", gmax=0.3)
        assert result["ess_delta"] == pytest.approx(0.02)

    def test_failure_step_unchanged(self):
        """CS≤-0.2 且 SL → ess_delta=-0.05（保持不变）"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        result = engine.apply_reward(cs=-0.5, outcome="SL", cluster_id="c1", ess_id="e1", gmax=0.3)
        assert result["ess_delta"] == pytest.approx(-0.05)


class TestESSEMA:
    """EMA衰减：ESS更新引入指数移动平均，近期样本权重更高"""

    def test_ema_decay_reduces_old_sample_impact(self):
        """连续多笔低CS交易后，旧高CS交易的影响被EMA衰减"""
        from dreambuddy_evolution.core.ess_ema import ESSAdaptiveUpdater

        updater = ESSAdaptiveUpdater(ema_alpha=0.3)
        # 旧交易: 高CS +0.05（直接设置EMA）
        updater.update(ess_delta=0.05, cs=0.95)
        assert updater._ema_delta == pytest.approx(0.05)
        # 连续10笔低CS +0.02 交易，EMA应被拉向0.02
        for _ in range(10):
            updater.update(ess_delta=0.02, cs=0.8)
        # 经过多笔低CS交易后，EMA应更接近0.02而非0.05
        assert abs(updater._ema_delta - 0.02) < abs(updater._ema_delta - 0.05)

    def test_ema_alpha_default_in_range(self):
        """EMA alpha 默认值在 (0, 1]"""
        from dreambuddy_evolution.core.ess_ema import ESSAdaptiveUpdater
        updater = ESSAdaptiveUpdater()
        assert 0.0 < updater.ema_alpha <= 1.0

    def test_high_cs_receives_full_step(self):
        """高CS交易获得完整步长（不衰减）"""
        from dreambuddy_evolution.core.ess_ema import ESSAdaptiveUpdater
        updater = ESSAdaptiveUpdater(ema_alpha=0.5)
        effective = updater.effective_delta(ess_delta=0.05, cs=0.95)
        assert effective == pytest.approx(0.05)
