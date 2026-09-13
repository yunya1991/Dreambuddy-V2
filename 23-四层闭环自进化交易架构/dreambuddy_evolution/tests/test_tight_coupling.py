"""
dreambuddy-v2 紧耦合流 TDD 测试套件
蓝图根: §一·七 两条链路紧耦合流 (§0.7 RippleEngine + §1.6 ReflectionEngine 顺序串联)

7 步闭环: 观察→推断→实验→测量→反思→学习→泛化→回馈
"""
import sys
import json
import math
import numpy as np
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ==============================================================================
# TR-RE: RippleEngine (§0.7 调研-观察-总结 涟漪扩散引擎)
# ==============================================================================
class TestRippleEngine:
    """RippleEngine: 龙头检测 + R1/R2/R3 涟漪扩散 → RI ∈ [0,1]"""

    def test_TR_RE_01_ripple_source_detection_basic(self):
        """龙头检测: leader 在 S_up 簇 + ESS_top1 方向一致 + 放量"""
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        re = RippleEngine()
        # 龙头候选: R_up < R_down (上涨有利), ESS top 方向=long, vol_ratio≥2.0
        source = {
            "symbol": "BTC",
            "r_vector": {"R_up": 0.2, "R_down": 0.8, "R_smooth": 0.3,
                         "R_flow": 0.6, "R_reflexivity": 0.4},
            "ess_top_direction": "long",
            "vol_5": 5000.0,
            "vol_20": 2000.0,
            "liq_index_change": 0.35,
            "scale_class": "Classical",
        }
        is_source = re.detect_ripple_source(source)
        assert is_source is True

    def test_TR_RE_02_ripple_source_reject_quantum(self):
        """Quantum 档龙头排除 (§0.7.5)"""
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        re = RippleEngine()
        source = {
            "symbol": "PEPE",
            "r_vector": {"R_up": 0.1, "R_down": 0.9, "R_smooth": 0.2,
                         "R_flow": 0.7, "R_reflexivity": 0.3},
            "ess_top_direction": "long",
            "vol_5": 10000.0, "vol_20": 3000.0,
            "liq_index_change": 0.5,
            "scale_class": "Quantum",  # Quantum 排除
        }
        assert re.detect_ripple_source(source) is False

    def test_TR_RE_03_ripple_source_reject_low_volume(self):
        """vol_5/vol_20 < 2.0 → 不是真石头"""
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        re = RippleEngine()
        source = {
            "symbol": "BTC",
            "r_vector": {"R_up": 0.2, "R_down": 0.8, "R_smooth": 0.3,
                         "R_flow": 0.6, "R_reflexivity": 0.4},
            "ess_top_direction": "long",
            "vol_5": 3000.0, "vol_20": 2500.0,  # ratio=1.2 < 2.0
            "liq_index_change": 0.35,
            "scale_class": "Classical",
        }
        assert re.detect_ripple_source(source) is False

    def test_TR_RE_04_compute_ri_three_layers(self):
        """R1/R2/R3 三层涟漪 → RI = 0.4·s1 + 0.35·s2 + 0.25·s3"""
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        re = RippleEngine()
        ripples = {
            "R1": {"hits": 8, "candidates": 10, "delta_t_hours": 1.0, "tau": 2.0},
            "R2": {"hits": 5, "candidates": 10, "delta_t_hours": 2.0, "tau": 4.0},
            "R3": {"hits": 3, "candidates": 10, "delta_t_hours": 4.0, "tau": 8.0},
        }
        ri = re.compute_ri(ripples)
        assert 0.0 <= ri <= 1.0
        # s1 = (8/10)*exp(-1/2) = 0.8*0.6065 = 0.485
        # s2 = (5/10)*exp(-2/4) = 0.5*0.6065 = 0.303
        # s3 = (3/10)*exp(-4/8) = 0.3*0.6065 = 0.182
        # RI = 0.4*0.485 + 0.35*0.303 + 0.25*0.182 = 0.194 + 0.106 + 0.045 = 0.345
        assert ri == pytest.approx(0.345, abs=0.05)

    def test_TR_RE_05_ri_threshold_actions(self):
        """RI 阈值动作表 (§0.7.3)"""
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        re = RippleEngine()
        # RI < 0.30 → 不动作
        a1 = re.get_ri_action(0.20)
        assert a1["cbr_boost"] == 0.0
        # RI 0.30-0.55 → CBR +10%
        a2 = re.get_ri_action(0.40)
        assert a2["cbr_boost"] == pytest.approx(0.10)
        # RI 0.55-0.75 → CBR +20% + ESS ×1.05
        a3 = re.get_ri_action(0.65)
        assert a3["cbr_boost"] == pytest.approx(0.20)
        assert a3["ess_temp_mult"] == pytest.approx(1.05)
        # RI ≥ 0.75 → CBR +25% + ESS ×1.10 + A2 调研
        a4 = re.get_ri_action(0.80)
        assert a4["cbr_boost"] == pytest.approx(0.25)
        assert a4["ess_temp_mult"] == pytest.approx(1.10)
        assert a4.get("trigger_a2") is True

    def test_TR_RE_06_fail_open_ri_neutral(self):
        """crash/缺数据 → RI=0.50 中性降级"""
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        re = RippleEngine()
        ri = re.compute_ri({})  # 空 ripples
        assert ri == pytest.approx(0.50, abs=0.01)
        action = re.get_ri_action(0.50)
        # RI=0.50 落入 0.30-0.55 档 → CBR +10%
        assert action["cbr_boost"] == pytest.approx(0.10)


# ==============================================================================
# TR-RF: ReflectionEngine (§1.6 调查·反思·实践 三公理)
# ==============================================================================
class TestReflectionEngine:
    """ReflectionEngine: pre_trade_snapshot → CS → 四维奖惩"""

    def test_TR_RF_01_pre_trade_snapshot(self):
        """开仓瞬间快照记录"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        snap = rf.create_snapshot(
            symbol="BTC", u_open=0.1, action="long",
            level0_dstar="long", ess_id="ST-V15-A", ess_dir="long",
            cbr_sim=0.82, cbr_top1_outcome="TP", cluster_id="S_up_3",
        )
        assert snap["symbol"] == "BTC"
        assert snap["u_open"] == 0.1
        assert snap["level0_dstar"] == "long"
        assert snap["ess_dir"] == "long"
        assert snap["cluster_id"] == "S_up_3"

    def test_TR_RF_02_cs_calculation_correct_prediction(self):
        """三源预测全对 → CS≥0.7"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        snapshot = {
            "level0_dstar": "long", "ess_dir": "long",
            "cbr_top1_outcome": "TP", "cluster_id": "S_up_3",
        }
        outcome = {"real_direction": "long", "real_outcome": "TP"}
        cs = rf.calculate_cs(snapshot, outcome)
        # cos(long, long)=1, cos(long, long)=1, sign_match(TP, TP)=1
        # CS = 0.4*1 + 0.3*1 + 0.3*1 = 1.0
        assert cs == pytest.approx(1.0, abs=0.01)

    def test_TR_RF_03_cs_calculation_wrong_prediction(self):
        """三源全错 → CS≤-0.2"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        snapshot = {
            "level0_dstar": "long", "ess_dir": "long",
            "cbr_top1_outcome": "TP", "cluster_id": "S_up_3",
        }
        outcome = {"real_direction": "short", "real_outcome": "SL"}
        cs = rf.calculate_cs(snapshot, outcome)
        # cos(long, short)=-1, cos(long, short)=-1, sign_match(TP, SL)=-1
        # CS = 0.4*(-1) + 0.3*(-1) + 0.3*(-1) = -1.0
        assert cs == pytest.approx(-1.0, abs=0.01)

    def test_TR_RF_04_reward_table_correct_and_tp(self):
        """CS≥0.7 & TP → ESS +0.02"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        result = rf.apply_reward(cs=0.8, outcome="TP", cluster_id="S_up_3",
                                  ess_id="ST-V15-A", gmax=1.0)
        assert result["ess_delta"] == pytest.approx(0.02)
        assert result["gmax_mult"] == pytest.approx(1.0)  # 不变
        assert result["cluster_weight_mult"] == pytest.approx(1.0)  # +1 加权

    def test_TR_RF_05_punish_table_wrong_and_sl(self):
        """CS≤-0.2 & SL → ESS -0.05 + gmax×0.5"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        result = rf.apply_reward(cs=-0.5, outcome="SL", cluster_id="S_up_3",
                                  ess_id="ST-V15-A", gmax=1.0)
        assert result["ess_delta"] == pytest.approx(-0.05)
        assert result["gmax_mult"] == pytest.approx(0.5)

    def test_TR_RF_06_anti_pattern_luck_tp(self):
        """CS≤-0.2 & TP = 运气 → 不更新 ESS（反模式保护）"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        result = rf.apply_reward(cs=-0.5, outcome="TP", cluster_id="S_up_3",
                                  ess_id="ST-V15-A", gmax=1.0)
        assert result["ess_delta"] == 0.0  # 不奖励
        assert result.get("anti_pattern_flag") is True

    def test_TR_RF_07_false_failure_sl(self):
        """CS≥0.7 & SL = 假失败 → gmax×1.2 放宽"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        result = rf.apply_reward(cs=0.8, outcome="SL", cluster_id="S_up_3",
                                  ess_id="ST-V15-A", gmax=1.0)
        assert result["ess_delta"] == 0.0  # 不扣（方向对）
        assert result["gmax_mult"] == pytest.approx(1.2)

    def test_TR_RF_08_neutral_zone_no_update(self):
        """-0.2≤CS<0.7 → 不更新"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        rf = ReflectionEngine()
        result = rf.apply_reward(cs=0.3, outcome="TP", cluster_id="S_up_3",
                                  ess_id="ST-V15-A", gmax=1.0)
        assert result["ess_delta"] == 0.0
        assert result["gmax_mult"] == pytest.approx(1.0)


# ==============================================================================
# TR-TC: 紧耦合编排器 (§一·七 7步完整闭环)
# ==============================================================================
class TestTightCouplingOrchestrator:
    """观察→推断→实验→测量→反思→学习→泛化→回馈"""

    def test_TR_TC_01_observe_step(self):
        """步骤① 观察: RippleEngine 检测龙头 + 涟漪 → RI"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        market_data = {
            "leader_symbol": "BTC",
            "leader_r_vector": {"R_up": 0.2, "R_down": 0.8, "R_smooth": 0.8,
                                "R_flow": 0.6, "R_reflexivity": 0.5},
            "ess_top_direction": "long",
            "vol_5": 5000.0, "vol_20": 2000.0,
            "liq_index_change": 0.35,
            "scale_class": "Classical",
            "ripples": {
                "R1": {"hits": 8, "candidates": 10, "delta_t_hours": 1.0, "tau": 2.0},
                "R2": {"hits": 6, "candidates": 10, "delta_t_hours": 2.0, "tau": 4.0},
                "R3": {"hits": 4, "candidates": 10, "delta_t_hours": 4.0, "tau": 8.0},
            },
        }
        result = tco.observe(market_data)
        assert "ri" in result
        assert "is_ripple_source" in result
        assert result["is_ripple_source"] is True

    def test_TR_TC_02_hypothesize_step(self):
        """步骤② 推断: RI 阈值表 → 推断标记"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        obs = {"ri": 0.65, "is_ripple_source": True}
        hyp = tco.hypothesize(obs)
        assert hyp["inference_formed"] is True
        assert hyp["cbr_boost"] == pytest.approx(0.20)
        assert hyp["ess_temp_mult"] == pytest.approx(1.05)

    def test_TR_TC_03_no_inference_low_ri(self):
        """RI < 0.30 → 不推断"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        obs = {"ri": 0.20, "is_ripple_source": True}
        hyp = tco.hypothesize(obs)
        assert hyp["inference_formed"] is False

    def test_TR_TC_04_experiment_step(self):
        """步骤③ 实验: Level0 d* + 对齐 → 小仓 u=0.1 + snapshot"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        # wait cost = 0.8*0.5=0.4 > long cost=0.2 → d*=long
        r_vector = {"R_up": 0.2, "R_down": 0.8, "R_smooth": 0.8,
                    "R_flow": 0.6, "R_reflexivity": 0.5}
        hyp = {"inference_formed": True, "ess_dir": "long"}
        exp = tco.experiment(r_vector, hyp, symbol="BTC", ess_id="ST-V15-A",
                            cbr_sim=0.82, cluster_id="S_up_3")
        assert exp["u_open"] == pytest.approx(0.1)  # §1.7.6 硬上限
        assert "pre_trade_snapshot" in exp
        assert exp["pre_trade_snapshot"]["level0_dstar"] == "long"

    def test_TR_TC_05_experiment_wait_when_not_aligned(self):
        """d* = WAIT → 不建仓"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        r_vector = {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.1,
                    "R_flow": 0.5, "R_reflexivity": 0.1}  # wait cost=0.01 < 0.5
        hyp = {"inference_formed": True, "ess_dir": "long"}
        exp = tco.experiment(r_vector, hyp, symbol="BTC", ess_id="ST-V15-A",
                            cbr_sim=0.82, cluster_id="S_up_3")
        assert exp["u_open"] == 0.0  # WAIT = 不建仓
        assert exp["action"] == "WAIT"

    def test_TR_TC_06_reflect_step(self):
        """步骤⑤ 反思: snapshot + outcome → CS + 奖惩"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        snapshot = {"level0_dstar": "long", "ess_dir": "long",
                    "cbr_top1_outcome": "TP", "cluster_id": "S_up_3",
                    "ess_id": "ST-V15-A", "u_open": 0.1}
        outcome = {"real_direction": "long", "real_outcome": "TP"}
        result = tco.reflect(snapshot, outcome)
        assert "cs" in result
        assert result["cs"] >= 0.7
        # CS=1.0（全信号对齐）≥0.9 → 大步长 +0.05（Phase1.2 动态步长）
        assert result["ess_delta"] == pytest.approx(0.05)

    def test_TR_TC_07_full_cycle(self):
        """完整 7 步闭环: observe→hypothesize→experiment→measure→reflect→learn→feedback"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        # ① 观察
        market_data = {
            "leader_symbol": "BTC",
            "leader_r_vector": {"R_up": 0.2, "R_down": 0.8, "R_smooth": 0.8,
                                "R_flow": 0.6, "R_reflexivity": 0.5},
            "ess_top_direction": "long",
            "vol_5": 5000.0, "vol_20": 2000.0,
            "liq_index_change": 0.35,
            "scale_class": "Classical",
            "ripples": {
                "R1": {"hits": 9, "candidates": 10, "delta_t_hours": 0.5, "tau": 2.0},
                "R2": {"hits": 7, "candidates": 10, "delta_t_hours": 1.0, "tau": 4.0},
                "R3": {"hits": 5, "candidates": 10, "delta_t_hours": 2.0, "tau": 8.0},
            },
        }
        obs = tco.observe(market_data)
        # ② 推断
        hyp = tco.hypothesize(obs)
        assert hyp["inference_formed"] is True
        # ③ 实验
        exp = tco.experiment(obs["leader_r_vector"], hyp, symbol="BTC",
                            ess_id="ST-V15-A", cbr_sim=0.82, cluster_id="S_up_3")
        # ④ 测量 (模拟 TP)
        measure = tco.measure(exp, outcome_direction="long", outcome_result="TP")
        # ⑤ 反思
        refl = tco.reflect(exp["pre_trade_snapshot"], measure)
        assert refl["cs"] >= 0.7
        # ⑥ 学习（CS=1.0≥0.9 → +0.05）
        learned = tco.learn(refl)
        assert learned["ess_delta"] == pytest.approx(0.05)
        # ⑦ 回馈
        feedback = tco.feedback(learned)
        assert "updated_ess_direction" in feedback

    def test_TR_TC_08_fail_open_never_crash(self):
        """全空输入 → 不崩，输出 WAIT"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator()
        result = tco.observe({})
        assert result.get("ri") == pytest.approx(0.50, abs=0.01)  # FO 降级
        hyp = tco.hypothesize(result)
        assert hyp["inference_formed"] is False  # RI 低 → 不推断

    def test_TR_TC_09_mvp_loose_coupling(self):
        """MVP 阶段: RI≥0.75 → 只推 Lark，不自动建仓"""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        tco = TightCouplingOrchestrator(mode="MVP")
        obs = {"ri": 0.80, "is_ripple_source": True}
        hyp = tco.hypothesize(obs)
        # MVP 模式: 推断标记=True 但 auto_execute=False
        assert hyp["inference_formed"] is True
        assert hyp.get("auto_execute") is False
        assert hyp.get("lark_notification") is True
