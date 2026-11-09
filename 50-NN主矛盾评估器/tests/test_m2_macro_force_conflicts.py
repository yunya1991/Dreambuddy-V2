"""M2 测试：宏观力传导 + 三类矛盾（SPEC-M2）。

覆盖：
  M2-1: F_macro 四分量计算（BTC 恒等、层门、分量权重、t_arrive、fail-open）
  M2-2: macro_micro_conflict（sign 反向 + 阈值 + horizon 仲裁）
  M2-3: temporal_conflict（t_arrive 到达窗口衰减）
  M2-4: inter_dimension_conflict（D1 vs D2/D4）
  M2-5: deduplicate_conflicts（同标的同维度只一个，temporal 优先）
"""

from __future__ import annotations

from core.contradiction import (
    deduplicate_conflicts,
    detect_all_conflicts,
    detect_inter_dimension_conflicts,
    detect_macro_micro_conflicts,
    detect_temporal_conflicts,
)
from core.macro_force import (
    LAYER_COMPONENT_WEIGHTS,
    MacroForce,
    compute_macro_forces,
    f_cycle_from_state,
    normalize_symbol,
)

# ── fixtures ──────────────────────────────────────────────────────


def _cycle_state(last_change="down", regime="bull", above=2, below=1):
    return {
        "real_cycle": {"last_change": last_change, "confidence": "high"},
        "technical_anchor": {
            "assets": {f"a{i}": {"above": True} for i in range(above)}
            | {f"b{i}": {"above": False} for i in range(below)},
            "regime": regime,
        },
    }


def _sector(state="expanding", meme_gap=-7.0, layers=None, medians=None):
    return {
        "layers": layers
        or {
            "L1_anchor": ["BTC/USDT"],
            "L2_major": ["ETH/USDT"],
        },
        "assets": {
            "BTC/USDT": {"layer": "L1_anchor", "momentum_3m_pct": 5.0},
            "ETH/USDT": {"layer": "L2_major", "momentum_3m_pct": 10.0},
        },
        "layer_median_momentum_3m_pct": medians or {"L1_anchor": 5.0, "L2_major": 10.0},
        "transmission": {"state": state, "meme_vs_major_gap_pct": meme_gap},
    }


def _resonance(corr0=0.9, lag_profile=None, granger_p=0.01):
    return {
        "assets": {
            "ETH/USDT": {
                "corr0": corr0,
                "lag_profile": lag_profile or [0.9, 0.8, 0.4, 0.2],
                "beta": 1.3,
                "down_corr": 1.0,
                "granger_p": granger_p,
            }
        }
    }


def _macro_force(
    symbol="ETH",
    layer="L2_major",
    d1=0.8,
    d2=-0.5,
    d4=0.3,
    washout=0.0,
    f_cycle=1.0,
    corr0=0.9,
    t_arrive=2.0,
    layer_gate=1.0,
):
    return MacroForce(
        symbol=symbol,
        layer=layer,
        d1_trend=d1,
        d2_fund=d2,
        d4_sentiment=d4,
        washout=washout,
        f_cycle=f_cycle,
        corr0=corr0,
        layer_gate=layer_gate,
        t_arrive_days=t_arrive,
        degraded=[],
    )


# ══════════════════════════════════════════════════════════════════
# M2-1: F_macro 四分量
# ══════════════════════════════════════════════════════════════════


class TestFCycle:
    def test_rate_cut_bull_above_ma200_returns_positive(self):
        # down(+1) + above majority(+1) + bull(+1) = 3/3 = 1.0
        assert f_cycle_from_state(_cycle_state("down", "bull", 2, 1)) == 1.0

    def test_rate_hike_bear_below_ma200_returns_negative(self):
        # up(-1) + below majority(-1) + bear(-1) = -1.0
        assert f_cycle_from_state(_cycle_state("up", "bear", 1, 2)) == -1.0

    def test_empty_state_fail_open_zero(self):
        assert f_cycle_from_state({}) == 0.0
        assert f_cycle_from_state(None) == 0.0

    def test_flat_plateau_no_ma200_zero(self):
        cs = {"real_cycle": {"last_change": "flat", "state": "plateau"}}
        assert f_cycle_from_state(cs) == 0.0


class TestComputeMacroForces:
    def test_btc_identity_no_corr0_attenuation(self):
        """L1 龙头直接承接 F_cycle，不乘 corr0。"""
        forces = compute_macro_forces(_cycle_state(), _resonance(), _sector(), {})
        btc = forces["BTC"]
        assert btc.f_cycle == 1.0
        assert btc.d1_trend == 1.0 * LAYER_COMPONENT_WEIGHTS["L1_anchor"]["D1"]

    def test_eth_corr0_attenuation(self):
        """L2 = F_cycle × corr0 × layer_gate。"""
        forces = compute_macro_forces(_cycle_state(), _resonance(corr0=0.9), _sector(), {})
        eth = forces["ETH"]
        # base = 1.0 * 0.9 * 1.0 = 0.9
        assert abs(eth.d1_trend - 0.9 * LAYER_COMPONENT_WEIGHTS["L2_major"]["D1"]) < 1e-9

    def test_layer_gate_contracting_halves_non_l1(self):
        """contracting 时非 L1 层 layer_gate=0.5。"""
        forces = compute_macro_forces(
            _cycle_state(), _resonance(corr0=1.0), _sector(state="contracting"), {}
        )
        eth = forces["ETH"]
        assert eth.layer_gate == 0.5
        # base = 1.0 * 1.0 * 0.5 = 0.5
        assert abs(eth.d1_trend - 0.5 * LAYER_COMPONENT_WEIGHTS["L2_major"]["D1"]) < 1e-9

    def test_layer_gate_does_not_affect_l1(self):
        forces = compute_macro_forces(
            _cycle_state(), _resonance(), _sector(state="contracting"), {}
        )
        assert forces["BTC"].layer_gate == 1.0

    def test_t_arrive_from_lag_profile(self):
        """首个 |corr| < 0.5×|corr0| 的偏移日 = t_arrive。"""
        # corr0=0.9, half=0.45; lag=[0.9,0.8,0.4,...] → idx2=0.4<0.45 → t_arrive=2
        forces = compute_macro_forces(
            _cycle_state(),
            _resonance(corr0=0.9, lag_profile=[0.9, 0.8, 0.4, 0.2]),
            _sector(),
            {},
        )
        assert forces["ETH"].t_arrive_days == 2.0

    def test_t_arrive_none_when_no_decay_below_half(self):
        forces = compute_macro_forces(
            _cycle_state(),
            _resonance(corr0=0.9, lag_profile=[0.9, 0.85, 0.8, 0.78]),
            _sector(),
            {},
        )
        assert forces["ETH"].t_arrive_days is None

    # ── G2 门禁：Granger 不显著 → t_arrive 禁用 ──────────────

    def test_g2_granger_not_significant_disables_t_arrive(self):
        forces = compute_macro_forces(
            _cycle_state(),
            _resonance(corr0=0.9, lag_profile=[0.9, 0.8, 0.4, 0.2], granger_p=0.30),
            _sector(),
            {},
        )
        eth = forces["ETH"]
        assert eth.t_arrive_days is None
        assert "granger_not_significant" in eth.degraded

    def test_g2_granger_missing_p_disables_t_arrive(self):
        forces = compute_macro_forces(
            _cycle_state(),
            _resonance(corr0=0.9, lag_profile=[0.9, 0.8, 0.4, 0.2], granger_p=None),
            _sector(),
            {},
        )
        eth = forces["ETH"]
        assert eth.t_arrive_days is None
        assert "granger_not_significant" in eth.degraded

    def test_g2_granger_significant_enables_t_arrive(self):
        forces = compute_macro_forces(
            _cycle_state(),
            _resonance(corr0=0.9, lag_profile=[0.9, 0.8, 0.4, 0.2], granger_p=0.01),
            _sector(),
            {},
        )
        eth = forces["ETH"]
        assert eth.t_arrive_days == 2.0
        assert "granger_not_significant" not in eth.degraded

    def test_fail_open_no_resonance_uses_corr0_one(self):
        forces = compute_macro_forces(_cycle_state(), None, _sector(), {})
        assert forces["ETH"].corr0 == 1.0
        assert forces["ETH"].d1_trend == 1.0 * 1.0 * 1.0 * LAYER_COMPONENT_WEIGHTS["L2_major"]["D1"]

    def test_fail_open_no_sector_returns_empty(self):
        forces = compute_macro_forces(_cycle_state(), _resonance(), None, {})
        assert forces == {}

    def test_all_components_in_range(self):
        forces = compute_macro_forces(_cycle_state(), _resonance(), _sector(), {})
        for f in forces.values():
            for comp in (f.d1_trend, f.d2_fund, f.d4_sentiment, f.washout):
                assert -1.0 <= comp <= 1.0

    def test_normalize_symbol(self):
        assert normalize_symbol("BTC-USDT-SWAP") == "BTC"
        assert normalize_symbol("ETH/USDT") == "ETH"
        assert normalize_symbol("SOL") == "SOL"

    def test_washout_verdict_sets_reversal_force(self):
        wv = {"ETH/USDT": {"verdict": "washout", "confidence": 0.8}}
        # base > 0 (F_cycle=1.0) → washout force = -conf
        forces = compute_macro_forces(_cycle_state(), _resonance(), _sector(), wv)
        assert forces["ETH"].washout == -0.8


# ══════════════════════════════════════════════════════════════════
# M2-2: macro_micro_conflict
# ══════════════════════════════════════════════════════════════════


class TestMacroMicroConflict:
    def test_opposite_signs_above_threshold_triggers(self):
        mf = {"ETH": _macro_force(d1=0.8)}
        micro = {"ETH-USDT-SWAP": {"D1": -0.6}}
        conflicts = detect_macro_micro_conflicts(mf, micro, micro_horizon="hours")
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c["type"] == "macro_micro_conflict"
        assert c["symbol"] == "ETH"
        assert c["dimension"] == "D1"
        # micro horizon=hours ≤1d → micro主导 (0.3, 0.7)
        assert c["macro_weight"] == 0.3
        assert c["micro_weight"] == 0.7
        assert c["resolution"] == "micro"

    def test_same_sign_no_conflict(self):
        mf = {"ETH": _macro_force(d1=0.8)}
        micro = {"ETH": {"D1": 0.6}}
        assert detect_macro_micro_conflicts(mf, micro) == []

    def test_below_threshold_no_conflict(self):
        mf = {"ETH": _macro_force(d1=0.8)}
        micro = {"ETH": {"D1": -0.2}}  # |micro| < 0.3
        assert detect_macro_micro_conflicts(mf, micro) == []

    def test_long_horizon_macro_dominant(self):
        mf = {"ETH": _macro_force(d1=0.8)}
        micro = {"ETH": {"D1": -0.6}}
        conflicts = detect_macro_micro_conflicts(mf, micro, micro_horizon="weeks")
        assert conflicts[0]["macro_weight"] == 0.7
        assert conflicts[0]["resolution"] == "macro"

    def test_transition_horizon_equal_weights(self):
        mf = {"ETH": _macro_force(d1=0.8)}
        micro = {"ETH": {"D1": -0.6}}
        conflicts = detect_macro_micro_conflicts(mf, micro, micro_horizon="days")
        # days=1.0 → exactly MICRO_DOMINANT threshold → micro主导
        assert conflicts[0]["micro_weight"] == 0.7


# ══════════════════════════════════════════════════════════════════
# M2-3: temporal_conflict
# ══════════════════════════════════════════════════════════════════


class TestTemporalConflict:
    def test_before_arrival_micro_decays(self):
        # t_arrive=2, now=0 → decay = 1 - (2-0)/2 = 0.0
        mf = {"ETH": _macro_force(d1=0.8, t_arrive=2.0)}
        micro = {"ETH": {"D1": -0.6}}
        conflicts = detect_temporal_conflicts(mf, micro, now_offset_days=0.0)
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c["type"] == "temporal_conflict"
        assert c["t_arrive"] == 2.0
        assert c["micro_decay"] == 0.0
        assert c["resolution"] == "micro_transition"

    def test_near_arrival_converging(self):
        # t_arrive=2, now=1.5 → decay = 1 - 0.5/2 = 0.75 > 0.5 → converging
        mf = {"ETH": _macro_force(d1=0.8, t_arrive=2.0)}
        micro = {"ETH": {"D1": -0.6}}
        conflicts = detect_temporal_conflicts(mf, micro, now_offset_days=1.5)
        assert conflicts[0]["micro_decay"] == 0.75
        assert conflicts[0]["resolution"] == "converging"

    def test_after_arrival_macro_dominant(self):
        mf = {"ETH": _macro_force(d1=0.8, t_arrive=2.0)}
        micro = {"ETH": {"D1": -0.6}}
        conflicts = detect_temporal_conflicts(mf, micro, now_offset_days=3.0)
        assert conflicts[0]["micro_decay"] == 0.0
        assert conflicts[0]["resolution"] == "macro_dominant"

    def test_no_t_arrive_no_temporal_conflict(self):
        mf = {"ETH": _macro_force(d1=0.8, t_arrive=None)}
        micro = {"ETH": {"D1": -0.6}}
        assert detect_temporal_conflicts(mf, micro) == []

    def test_same_sign_no_temporal_conflict(self):
        mf = {"ETH": _macro_force(d1=0.8, t_arrive=2.0)}
        micro = {"ETH": {"D1": 0.6}}
        assert detect_temporal_conflicts(mf, micro) == []


# ══════════════════════════════════════════════════════════════════
# M2-4: inter_dimension_conflict
# ══════════════════════════════════════════════════════════════════


class TestInterDimensionConflict:
    def test_d1_long_d2_short_triggers(self):
        mf = {"ETH": _macro_force(d1=0.8, d2=-0.6, d4=0.1)}
        conflicts = detect_inter_dimension_conflicts(mf)
        dims = {tuple(c["dimensions"]) for c in conflicts}
        assert ("D1", "D2") in dims
        # D4=0.1 < 0.3 → no D1-D4 conflict
        assert all("D4" not in c["dimensions"] for c in conflicts)

    def test_d1_long_d4_short_triggers(self):
        mf = {"ETH": _macro_force(d1=0.8, d2=0.1, d4=-0.6)}
        conflicts = detect_inter_dimension_conflicts(mf)
        assert any(set(c["dimensions"]) == {"D1", "D4"} for c in conflicts)

    def test_same_sign_no_conflict(self):
        mf = {"ETH": _macro_force(d1=0.8, d2=0.6, d4=0.5)}
        assert detect_inter_dimension_conflicts(mf) == []

    def test_resolution_picks_stronger(self):
        # |d1|=0.8 > |d2|=0.6 → resolution=D1
        mf = {"ETH": _macro_force(d1=0.8, d2=-0.6)}
        conflicts = detect_inter_dimension_conflicts(mf)
        d1d2 = next(c for c in conflicts if set(c["dimensions"]) == {"D1", "D2"})
        assert d1d2["resolution"] == "D1"


# ══════════════════════════════════════════════════════════════════
# M2-5: deduplicate_conflicts
# ══════════════════════════════════════════════════════════════════


class TestDeduplication:
    def test_temporal_takes_priority_over_macro_micro(self):
        mf = {"ETH": _macro_force(d1=0.8, t_arrive=2.0)}
        micro = {"ETH": {"D1": -0.6}}
        raw = detect_macro_micro_conflicts(mf, micro) + detect_temporal_conflicts(
            mf, micro, now_offset_days=0.0
        )
        # 去重前同 (ETH, D1) 有 2 条
        assert len(raw) == 2
        deduped = deduplicate_conflicts(raw)
        assert len(deduped) == 1
        assert deduped[0]["type"] == "temporal_conflict"

    def test_inter_dimension_kept_separately(self):
        mf = {"ETH": _macro_force(d1=0.8, d2=-0.6, t_arrive=2.0)}
        micro = {"ETH": {"D1": -0.6}}
        all_c = detect_all_conflicts(mf, micro, now_offset_days=0.0)
        types = {c["type"] for c in all_c}
        # temporal(D1) + inter_dimension(D1,D2) 都保留（key 不同）
        assert "temporal_conflict" in types
        assert "inter_dimension_conflict" in types

    def test_detect_all_returns_deduplicated(self):
        # d2=-0.5 会产生 inter_dimension(D1,D2)；D1 维度 temporal 与 macro_micro 去重只留 temporal
        mf = {"ETH": _macro_force(d1=0.8, t_arrive=2.0)}
        micro = {"ETH": {"D1": -0.6}}
        all_c = detect_all_conflicts(mf, micro, now_offset_days=0.0)
        types = [c["type"] for c in all_c]
        # temporal(D1) + inter_dimension(D1,D2) 都在；macro_micro 被 temporal 取代
        assert "temporal_conflict" in types
        assert "inter_dimension_conflict" in types
        assert "macro_micro_conflict" not in types
        # 同一 (ETH, D1) 维度只出现一次
        d1_conflicts = [c for c in all_c if c.get("dimension") == "D1"]
        assert len(d1_conflicts) == 1

    def test_no_t_arrive_falls_back_to_macro_micro(self):
        mf = {"ETH": _macro_force(d1=0.8, d2=0.0, t_arrive=None)}
        micro = {"ETH": {"D1": -0.6}}
        all_c = detect_all_conflicts(mf, micro)
        assert len(all_c) == 1
        assert all_c[0]["type"] == "macro_micro_conflict"
