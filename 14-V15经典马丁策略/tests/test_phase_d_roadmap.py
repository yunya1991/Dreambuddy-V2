"""
Phase D (MVP) TDD 测试套件（RED 阶段初稿：全部应失败）

覆盖：
  T1. PhaseDGateway G-D1：PatchTST 预测回撤≤-32% 或 BiLSTM P_bust≥0.60 → 建议 Skip Open
  T2. PhaseDGateway G-D1 边界：AI 永远不能强制开仓（baseline_wait=True 时 must_skip=True）
  T3. PhaseDGateway G-D2：BiLSTM P_bust≥0.55 → 缩加仓档（移除 addon4）
  T4. PhaseDGateway G-D3：Timing UNCLEAR + drawdown>-10% + P_bust<0.30 → 放宽 timing_score×1.05
  T5. §3.3 边界 clamp 公式：X_clamped = clamp(X_ai, X_base*LOWER, X_base*UPPER) 及外层铁壳
  T6. phase_d_dataset_generator：单轨迹生成 → 返回 (bilstm_input_dict, patchtst_input_array, label_bust, label_maxdd)
  T7. ai_boundary_scaler：S_bt 合成得分 ≥1.20 → K_bound=1.20，<1.00 → ValueError(不允许启用)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))


# ================================================================
# T1 · G-D1：Skip Open 闸门
# ================================================================
class TestGD1SkipOpen:
    def test_patchtst_drawdown_exceeds_32pct_suggests_skip(self):
        """PatchTST 预测未来 24h 最大回撤为 -40% (<=-32%阈值) → 应建议 Skip"""
        from phase_d_gateway import PhaseDGateway  # 会 ImportError (RED)

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001  TDD helper
            mock_patchtst_drawdown=-0.40,
            mock_bilstm_p_bust=0.20,
        )
        ctx = {"coin": "SOL", "position_level": 0, "timing_score": 0.80}
        assert gw.should_skip_open(ctx) is True
        assert gw.last_gate_code == "G-D1-SKIP-DRAWDOWN"

    def test_bilstm_p_bust_exceeds_60pct_suggests_skip(self):
        """BiLSTM 爆仓概率 70% (≥60%阈值) → 应建议 Skip"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.05,
            mock_bilstm_p_bust=0.70,
        )
        ctx = {"coin": "SOL", "position_level": 0, "timing_score": 0.80}
        assert gw.should_skip_open(ctx) is True
        assert gw.last_gate_code == "G-D1-SKIP-BUST"

    def test_safe_condition_does_not_skip(self):
        """回撤仅 -5%、爆仓概率 20% → 不触发 G-D1"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.05,
            mock_bilstm_p_bust=0.20,
        )
        ctx = {"coin": "SOL", "position_level": 0, "timing_score": 0.80}
        assert gw.should_skip_open(ctx) is False
        assert gw.last_gate_code is None


# ================================================================
# T2 · G-D1 最优先级边界：AI 只能否决开仓，不可强制开仓
# ================================================================
class TestGD1HighestPriorityRule:
    def test_baseline_wait_forbids_open_even_if_ai_loves_it(self):
        """§3.3 最高优先级规则：baseline=WAIT 时，AI 任何预测都必须返回 skip"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.01,  # AI 极其乐观
            mock_bilstm_p_bust=0.001,
        )
        ctx = {
            "coin": "BTC",
            "baseline_can_open": False,  # 基线说 WAIT (最核心输入)
            "position_level": 0,
            "timing_score": 0.90,
        }
        must_skip, reason = gw.should_skip_open_with_baseline(ctx)
        assert must_skip is True, "基线WAIT时，AI必须SKIP，绝不能强开仓"
        assert "baseline_wait" in reason


# ================================================================
# T3 · G-D2：缩加仓档
# ================================================================
class TestGD2TrimAddons:
    def test_p_bust_55pct_trims_deepest_addon(self):
        """BiLSTM P_bust=58% ≥ 55% 阈值 → 去除 addon4 (max_addons 从 4→3)"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.08,
            mock_bilstm_p_bust=0.58,
        )
        budgets = {"addon1_usd": 5.0, "addon2_usd": 10.0, "addon3_usd": 20.0, "addon4_usd": 35.0}
        eff, trimmed = gw.compute_effective_max_addons(
            coin="ARB", pos={"level": 2}, baseline_max_addons=4, addon_budgets=budgets
        )
        assert eff == 3, "G-D2 触发后 max_addons 必须从 4 缩到 3"
        assert "addon4_usd" not in trimmed or trimmed.get("addon4_usd", 0) == 0
        assert gw.last_gate_code == "G-D2-TRIM-ADDON4"

    def test_safe_condition_keeps_all_budgets(self):
        """P_bust 低时，不得自动缩档"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.08,
            mock_bilstm_p_bust=0.30,
        )
        budgets = {"addon1_usd": 5.0, "addon2_usd": 10.0, "addon3_usd": 20.0, "addon4_usd": 35.0}
        eff, trimmed = gw.compute_effective_max_addons(
            coin="ETH", pos={"level": 0}, baseline_max_addons=4, addon_budgets=budgets
        )
        assert eff == 4
        assert trimmed.get("addon4_usd") == 35.0


# ================================================================
# T4 · G-D3：Timing UNCLEAR 放松
# ================================================================
class TestGD3TimingRelaxation:
    def test_unclear_cond_relaxes_timing_score_105x(self):
        """UNCLEAR + dd=-8% (> -10%) + P_bust=15% (<30%) → timing_score 放大最多 1.05 倍"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.08,
            mock_bilstm_p_bust=0.15,
        )
        new_score, new_power = gw.apply_timing_relaxation(
            symbol="OP",
            timing_score=0.40,
            size_power=2.49,
            regime="UNCLEAR",
        )
        # 默认 G-D3 relax ≤ 1.05× → 0.40 × relax 但不得超过 0.40 × 1.05 = 0.42
        assert 0.40 <= new_score <= 0.40 * 1.05 + 1e-6
        # size_power 放宽 → 原值 2.49 × 0.9 = 2.241（必须往更小方向（放宽）走，不能反）
        assert new_power <= 2.49
        assert new_power >= 2.49 * 0.9 - 1e-6

    def test_not_unclear_does_not_relax(self):
        """不是 UNCLEAR regime 时，原值返回，严格不变"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.05,
            mock_bilstm_p_bust=0.10,
        )
        ns, np_ = gw.apply_timing_relaxation(
            symbol="BTC", timing_score=0.55, size_power=2.49, regime="BULLISH_3WAVE"
        )
        assert ns == pytest.approx(0.55)
        assert np_ == pytest.approx(2.49)

    def test_deep_drawdown_blocks_relaxation(self):
        """回撤 -15% (< -10% 阈值) → 即便 UNCLEAR 也不能放松"""
        from phase_d_gateway import PhaseDGateway

        gw = PhaseDGateway._for_testing_use_mock_predictor(  # noqa: SLF001
            mock_patchtst_drawdown=-0.15,
            mock_bilstm_p_bust=0.10,
        )
        ns, np_ = gw.apply_timing_relaxation(
            symbol="UNI", timing_score=0.40, size_power=2.49, regime="UNCLEAR"
        )
        assert ns == pytest.approx(0.40)
        assert np_ == pytest.approx(2.49)


# ================================================================
# T5 · §3.3 双层 clamp（相对边界 + 绝对铁壳）
# ================================================================
class TestBoundaryClamp33:
    def test_clamp_within_relative_bounds(self):
        """X_base=100, LOWER=0.7, UPPER=1.2 → 80~120；ai=150 → clamp 到 120"""
        from phase_d_gateway import apply_iron_clamp

        result = apply_iron_clamp(
            ai_value=150.0,
            baseline_value=100.0,
            relative_lower=0.70,
            relative_upper=1.20,
            absolute_lo=1.0,
            absolute_hi=1000.0,
        )
        assert result == pytest.approx(120.0)

    def test_iron_shell_overrides_relative(self):
        """就算相对边界允许，绝对铁壳 [10, 50]；上一步相对 clamp=120 → 再 clamp 到 50"""
        from phase_d_gateway import apply_iron_clamp

        result = apply_iron_clamp(
            ai_value=150.0,
            baseline_value=100.0,
            relative_lower=0.70,
            relative_upper=1.20,
            absolute_lo=10.0,
            absolute_hi=50.0,
        )
        assert result == pytest.approx(50.0)

    def test_max_addons_delta_only_negative_or_zero(self):
        """§3.3 max_addons：只允许 -1,0；AI 绝不允许 +1（扩到第5档）"""
        from phase_d_gateway import clamp_max_addons_delta

        # 善意 -1 OK
        assert clamp_max_addons_delta(-1, current_max=4) == 3
        # 保持不变 OK
        assert clamp_max_addons_delta(0, current_max=4) == 4
        # AI 想 +1 扩到第5档 → 强行拒绝，保持原 4
        assert clamp_max_addons_delta(+1, current_max=4) == 4, "AI 不能扩到第 5 档！"
        # AI 想一下 -2 干到 2 → 最多只允许 -1（§3.3 LOWER=-1 档）
        assert clamp_max_addons_delta(-2, current_max=4) == 3

    def test_base_position_pct_iron_shell(self):
        """§3.3 表第 7 行：绝对 pct ∈ [5%, 40%]；任何缩放不得越此区间"""
        from phase_d_gateway import apply_iron_clamp

        # 极端放大测试：基线=22, AI 想 ×10 → 220 → 被相对 UPPER 1.20×=26.4 → 再经铁壳 [5,40] → 26.4
        r = apply_iron_clamp(220, 22, 0.70, 1.20, 5.0, 40.0)
        assert 5 <= r <= 40
        assert r == pytest.approx(26.4)


# ================================================================
# T6 · phase_d_dataset_generator：标签生成形状与类型
# ================================================================
class TestPhaseDDatasetGenerator:
    def test_single_trajectory_returns_4tuple(self):
        """生成单条轨迹必须返回 4 元组：(bilstm_in, patchtst_in, label_bust, label_maxdd)"""
        from phase_d_dataset_generator import generate_single_trajectory_sample

        sample = generate_single_trajectory_sample(seed=42)
        assert isinstance(sample, tuple) and len(sample) == 4
        bilstm_in, patchtst_in, label_bust, label_maxdd = sample
        # BiLSTM 输入 = 60 timesteps × 5 (OHLCV) + 额外 7 个标量特征 ≈ 307 维向量
        assert "ohlcv" in bilstm_in
        assert "scalar_features" in bilstm_in
        assert len(bilstm_in["scalar_features"]) == 7
        # PatchTST 输入 = 120 timesteps × 5 (OHLCV)
        assert patchtst_in.shape == (120, 5)
        # 标签：bust 是 0/1 int；maxdd 是负百分比 float
        assert label_bust in (0, 1)
        assert isinstance(label_maxdd, float)
        assert label_maxdd <= 0.0


# ================================================================
# T7 · ai_boundary_scaler S_bt 公式 & K_bound 映射
# ================================================================
class TestAIBoundaryScaler:
    def test_s_bt_excellent_score_gives_k_120(self):
        """S_bt 优秀得分 → K_bound = 1.20（§3.4 规定 ≥1.20 → 1.20）
        用 1.30×收益 + 1.35×卡尔马 + 5/5 段正向 + MDD持平 → S_bt = 1.30*0.40 + 1.35*0.30 + 1.0*0.20 + 1.0*0.10 = 0.52+0.405+0.2+0.1 = 1.225"""
        from ai_boundary_scaler import compute_s_bt, k_bound_from_s_bt

        s = compute_s_bt(
            gross_return_ratio=1.30,  # +30% 相对基线
            calmar_ratio_ratio=1.35,  # 卡尔马显著更优
            wf_positive_segments=5,   # 5/5 段正向
            mdd_ratio=1.00,           # 回撤和基线一致
        )
        assert s >= 1.20, f"S_bt={s:.3f} 未达 1.20 档位下限"
        assert k_bound_from_s_bt(s) == pytest.approx(1.20)

    def test_s_bt_fail_raises(self):
        """S_bt < 1.00 → §3.2 铁律 2 禁止启用，函数必须抛出 ValueError"""
        from ai_boundary_scaler import k_bound_from_s_bt

        with pytest.raises(ValueError):
            k_bound_from_s_bt(0.92)

    def test_s_bt_just_pass_gives_k_080(self):
        """S_bt=1.02 (勉强过) → K_bound=0.80（边界收紧）"""
        from ai_boundary_scaler import k_bound_from_s_bt

        assert k_bound_from_s_bt(1.02) == pytest.approx(0.80)

    def test_s_bt_pass_gives_k_100(self):
        """S_bt=1.10 (合格) → K_bound=1.00（默认边界）"""
        from ai_boundary_scaler import k_bound_from_s_bt

        assert k_bound_from_s_bt(1.10) == pytest.approx(1.00)


if __name__ == "__main__":
    # 直接运行：确认所有用例都因 ImportError 或 AssertionError 失败（TDD RED）
    pytest.main([__file__, "-x", "-v", "--no-header"])
