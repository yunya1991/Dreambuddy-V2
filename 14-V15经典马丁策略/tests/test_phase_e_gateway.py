"""Phase E: PhaseEGateway + Deterministic Shield TDD 测试

覆盖路线图 §5.2 六盾 (DS1-DS6) + §5.1.2 五维动作 clamp + §3.3/§3.4 边界铁律。
"""
import pytest
from dataclasses import dataclass
from typing import Dict, Any, Tuple


# ── 辅助：构造测试用 allocation / base_params / s_state ──

def _baseline_alloc() -> Dict[str, Any]:
    return {
        "allowed": True,
        "base_usd": 26.0,
        "addon1_usd": 13.0,
        "addon2_usd": 26.0,
        "addon3_usd": 39.0,
        "addon4_usd": 52.0,
        "total_usd": 156.0,
        "per_coin_budget": 156.0,
    }


def _baseline_params() -> Dict[str, Any]:
    return {
        "addon_pct": 8.0,   # 百分数
        "tp_pct": 4.0,      # 百分数
    }


def _baseline_state() -> Dict[str, Any]:
    """34 维状态向量（dict 形式），所有中性值。"""
    return {
        # TimingGate (4)
        "timing_score": 0.5,
        "structure_match_score": 0.5,
        "retrace_quality_score": 0.5,
        "extension_chase_score": 0.5,
        # DirectionGate (5)
        "regime": "ACCUM",
        "short_enabled": False,
        "long_enabled": True,
        "btc_windvane_strength": 0.5,
        # RegimeManager (5)
        "regime_zone": 2,
        "days_in_current_zone": 10,
        # 持仓 (9)
        "position_level": 0,
        "avg_entry_price_pct_diff": 0.0,
        "unrealized_pnl_ratio": 0.0,
        "distance_to_liq_ratio": 0.80,
        # 波动 (8)
        "atr_14_pct": 0.03,
        "atr_14_zscore_30": 0.0,
        "realized_vol_30d": 0.04,
        "vol_zscore_60": 0.0,
        "btc_corr_30d": 0.8,
        "btc_rsi_14": 50.0,
        "swing_window_daily": 2,
        "swing_window_4h": 3,
        # 历史表现 (3)
        "recent_10_win_rate": 0.5,
        "recent_10_avg_pnl_ratio": 0.0,
        "max_drawdown_30d": 0.05,
        # DS 盾额外输入
        "account_margin_ratio": 0.10,
        "imr": 0.05,
        "coin_total_deployed": 0.0,
    }


class TestPhaseEGatewayDisabled:
    """enabled=False 时所有方法返回基线原值（铁律 1）。"""

    def test_disabled_apply_size_multipliers_returns_baseline(self):
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=False)
        alloc = _baseline_alloc()
        result = gw.apply_size_multipliers(alloc, _baseline_state())
        assert result["base_usd"] == 26.0
        assert result["addon1_usd"] == 13.0
        assert result["total_usd"] == 156.0

    def test_disabled_apply_param_multipliers_returns_baseline(self):
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=False)
        params = _baseline_params()
        result = gw.apply_param_multipliers("BTC", params, _baseline_state())
        assert result["addon_pct"] == 8.0
        assert result["tp_pct"] == 4.0

    def test_disabled_get_action_returns_neutral(self):
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=False)
        action = gw.get_action(_baseline_state())
        # 禁用时返回全 1.0 倍率 + max_addons_delta=0（=基线）
        assert action["addon_pct_mult"] == 1.0
        assert action["addon_size_mult"] == 1.0
        assert action["tp_pct_mult"] == 1.0
        assert action["base_position_mult"] == 1.0
        assert action["max_addons_delta"] == 0


class TestPhaseEGatewayActionClamp:
    """§3.3 边界铁壳 + §3.4 K_bound 缩放。"""

    def test_action_clamp_within_bounds(self):
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True, k_bound=1.0)
        # 注入 mock action（越界值），验证 clamp
        gw._mock_action = {
            "addon_pct_mult": 0.50,    # 下界 0.80
            "addon_size_mult": 0.30,   # 下界 0.60
            "tp_pct_mult": 0.50,       # 下界 0.80
            "base_position_mult": 0.50, # 下界 0.70
            "max_addons_delta": 1,     # 禁止 +1
        }
        action = gw.get_action(_baseline_state())
        assert action["addon_pct_mult"] == pytest.approx(0.80)
        assert action["addon_size_mult"] == pytest.approx(0.60)
        assert action["tp_pct_mult"] == pytest.approx(0.80)
        assert action["base_position_mult"] == pytest.approx(0.70)
        assert action["max_addons_delta"] == 0  # 不允许 +1

    def test_action_clamp_upper_bounds(self):
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True, k_bound=1.0)
        gw._mock_action = {
            "addon_pct_mult": 2.00,    # 上界 1.30
            "addon_size_mult": 3.00,   # 上界 1.50
            "tp_pct_mult": 2.00,       # 上界 1.30
            "base_position_mult": 2.00, # 上界 1.20
            "max_addons_delta": 1,     # 禁止 +1
        }
        action = gw.get_action(_baseline_state())
        assert action["addon_pct_mult"] == pytest.approx(1.30)
        assert action["addon_size_mult"] == pytest.approx(1.50)
        assert action["tp_pct_mult"] == pytest.approx(1.30)
        assert action["base_position_mult"] == pytest.approx(1.20)
        assert action["max_addons_delta"] == 0

    def test_k_bound_shrinks_bounds(self):
        """K_bound=0.80 时边界收紧（LOWER 更靠近 1.0，UPPER 更靠近 1.0）。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True, k_bound=0.80)
        gw._mock_action = {
            "addon_pct_mult": 0.70,
            "addon_size_mult": 0.50,
            "tp_pct_mult": 0.70,
            "base_position_mult": 0.60,
            "max_addons_delta": 0,
        }
        action = gw.get_action(_baseline_state())
        # K_bound=0.80 → LOWER_eff = 1 - (1-0.80)/0.80 = 1 - 0.25 = 0.75
        # 但绝对铁壳 [0.80, ...] 优先 → addon_pct_mult clamp 到 0.80
        assert action["addon_pct_mult"] >= 0.75  # 相对边界 vs 绝对铁壳取更紧的


class TestDeterministicShield:
    """§5.2 DS1-DS6 六盾测试。"""

    def test_ds1_margin_safety_rejects_size_up(self):
        """DS1: 保证金率不足时拒绝放大加仓。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.30,  # 想放大加仓
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }
        state = _baseline_state()
        # margin_ratio=0.11, IMR=0.05, (IMR+0.02)*1.5 = 0.105 → 0.11 > 0.105 → 缓冲区内
        state["account_margin_ratio"] = 0.11
        state["imr"] = 0.05
        action = gw.get_action(state)
        shielded = gw.shield_check(action, state, _baseline_alloc(), _baseline_params())
        assert shielded["addon_size_mult"] <= 1.0  # 被盾截断
        assert "DS1" in shielded.get("shield_flags", [])

    def test_ds2_per_coin_budget_rejects_size_up(self):
        """DS2: 单币种投入超预算 10% 时拒绝放大。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.40,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.20,
            "max_addons_delta": 0,
        }
        state = _baseline_state()
        state["coin_total_deployed"] = 180.0  # 超过 per_coin_budget=156 × 1.10=171.6
        action = gw.get_action(state)
        alloc = _baseline_alloc()
        shielded = gw.shield_check(action, state, alloc, _baseline_params())
        assert shielded["addon_size_mult"] <= 1.0
        assert shielded["base_position_mult"] <= 1.0
        assert "DS2" in shielded.get("shield_flags", [])

    def test_ds3_tp_absolute_clamp(self):
        """DS3: TP < 1.5% 或 > 12% 时 clamp 到边界。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True, k_bound=1.0)
        gw._mock_action = {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.0,
            "tp_pct_mult": 0.80,  # 会被 clamp 到 0.80（LOWER），然后盾检查绝对值
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }
        # base_tp=1.8% → 1.8 × 0.80 = 1.44% < 1.5% → DS3 触发
        low_tp_params = {"addon_pct": 8.0, "tp_pct": 1.8}
        action = gw.get_action(_baseline_state())
        shielded = gw.shield_check(action, _baseline_state(), _baseline_alloc(), low_tp_params)
        assert shielded["tp_pct_mult"] > 0.80  # 被盾调高到 1.5/1.8=0.833
        assert "DS3" in shielded.get("shield_flags", [])

    def test_ds4_addon_pct_absolute_clamp(self):
        """DS4: addon_pct < 3% 或 > 25% 时 clamp 到边界。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True, k_bound=1.0)
        gw._mock_action = {
            "addon_pct_mult": 0.80,  # 会被 clamp 到 0.80（LOWER），然后盾检查绝对值
            "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }
        # base_addon=3.5% → 3.5 × 0.80 = 2.8% < 3.0% → DS4 触发
        low_addon_params = {"addon_pct": 3.5, "tp_pct": 4.0}
        action = gw.get_action(_baseline_state())
        shielded = gw.shield_check(action, _baseline_state(), _baseline_alloc(), low_addon_params)
        assert shielded["addon_pct_mult"] > 0.80  # 被盾调高到 3.0/3.5=0.857
        assert "DS4" in shielded.get("shield_flags", [])

    def test_ds5_extreme_vol_rejects_amplify(self):
        """DS5: 极端波动 (vol_zscore > 2.5) 时禁止所有 *_mult > 1.0。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 1.20,
            "addon_size_mult": 1.40,
            "tp_pct_mult": 1.20,
            "base_position_mult": 1.15,
            "max_addons_delta": 0,
        }
        state = _baseline_state()
        state["vol_zscore_60"] = 3.0  # > 2.5
        action = gw.get_action(state)
        shielded = gw.shield_check(action, state, _baseline_alloc(), _baseline_params())
        assert shielded["addon_pct_mult"] <= 1.0
        assert shielded["addon_size_mult"] <= 1.0
        assert shielded["tp_pct_mult"] <= 1.0
        assert shielded["base_position_mult"] <= 1.0
        assert "DS5" in shielded.get("shield_flags", [])

    def test_ds6_consecutive_loss_rejects_expand(self):
        """DS6: 连亏熔断 (win_rate < 0.20, count >= 10) 时只允许缩档。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,  # 想保持，但 DS6 要求 -1
        }
        state = _baseline_state()
        state["recent_10_win_rate"] = 0.10
        state["recent_10_count"] = 10
        action = gw.get_action(state)
        shielded = gw.shield_check(action, state, _baseline_alloc(), _baseline_params())
        assert shielded["max_addons_delta"] == -1
        assert "DS6" in shielded.get("shield_flags", [])


class TestApplySizeMultipliers:
    """apply_size_multipliers 整合测试（动作 + 盾 + 分配）。"""

    def test_apply_multipliers_total_clamp(self):
        """§3.3 铁壳：各档总和 ≤ 原预算 × 1.10。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.50,  # 想放大 1.5x
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.20,  # 想放大 1.2x
            "max_addons_delta": 0,
        }
        result = gw.apply_size_multipliers(_baseline_alloc(), _baseline_state())
        original_total = 156.0
        assert result["total_usd"] <= original_total * 1.10 + 0.01  # 容差

    def test_apply_multipliers_max_addons_delta(self):
        """max_addons_delta=-1 → 最深档清零。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": -1,
        }
        result = gw.apply_size_multipliers(_baseline_alloc(), _baseline_state())
        assert result["addon4_usd"] == 0.0
        assert result["total_usd"] < 156.0


class TestApplyParamMultipliers:
    """apply_param_multipliers 整合测试。"""

    def test_apply_param_multipliers_normal(self):
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 1.10,
            "addon_size_mult": 1.0,
            "tp_pct_mult": 0.90,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }
        result = gw.apply_param_multipliers("BTC", _baseline_params(), _baseline_state())
        assert result["addon_pct"] == pytest.approx(8.8, abs=0.01)
        assert result["tp_pct"] == pytest.approx(3.6, abs=0.01)

    def test_apply_param_multipliers_ds_clamp(self):
        """addon_pct 被盾 clamp 到 ≥ 3%。"""
        from phase_e_gateway import PhaseEGateway
        gw = PhaseEGateway(enabled=True)
        gw._mock_action = {
            "addon_pct_mult": 0.30,  # 8% × 0.30 = 2.4% < 3%
            "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }
        result = gw.apply_param_multipliers("BTC", _baseline_params(), _baseline_state())
        assert result["addon_pct"] >= 3.0
