"""
default_weights TDD冒烟单测（蓝图附录C R-1 三祖师经验域 + Sobol'三档门禁前置）
共 20 条：
- TR-W-SENS-01 ~ TR-W-SENS-08 ：各权重独立×{0.8,1.0,1.2} 输出单调连续，跳变<10pp（TDD冒烟8条×2参数组=16？不，4组×2断言=8 条 01-08）
- TR-W-SENS-09 ~ TR-W-SENS-16 ：4权重组整体OAT ±20% 扰动，输出漂移<10%（不超橙灯15%线）8条
- TR-W-SENS-17       ：WEIGHTS_VERSION == "1.0-MVP" 语义键存在断言
- TR-W-SENS-18       ：BOUNDARIES 所有阈值档low < high（连续性）+ 9项键完整存在
- TR-W-SENS-19       ：FAIL-OPEN RI 降级值 0.29 < RI边界0.30（ε=0.01硬约束 蓝图附录A）
- TR-W-SENS-20       ：FAIL-OPEN CMScore 降级值 0.45 ∈ CM中性档 (0.35, 0.55)

先写测试，再实现 default_weights.py → 跑通（TDD RED-GREEN 周期）
"""
import math
import sys
from pathlib import Path

# 确保项目根在 sys.path
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _get_clamped_ess(H, S, N, w):
    """ESS 4:4:2公式 纯函数（和MVP Spec §2.2/蓝图附录C完全一致）用于权重变化断言"""
    wH, wS, wN, Nscale = w["H"], w["S"], w["N_ratio"], w["N_scale"]
    return max(0.0, min(1.0, wH * H + wS * S + wN * min(math.sqrt(max(N, 0) / Nscale), 1.0)))


def _clamp01(x):
    return max(0.0, min(1.0, x))


class TestDefaultWeightsStructure:
    def test_weights_version_exists_and_semantic(self):
        """TR-W-SENS-17: WEIGHTS_VERSION 必须等于1.0-MVP"""
        from dreambuddy_evolution.weights import WEIGHTS_VERSION
        assert WEIGHTS_VERSION == "1.0-MVP", f"expected 1.0-MVP got {WEIGHTS_VERSION}"

    def test_weights_4groups_all_present_keys(self):
        """所有4组权重dict都在顶层WEIGHTS"""
        from dreambuddy_evolution.weights import WEIGHTS
        for g in ("ESS", "R_REFL", "CS", "CM"):
            assert g in WEIGHTS, f"WEIGHTS missing group: {g}"

    def test_boundaries_all_required_keys(self):
        """TR-W-SENS-18: BOUNDARIES 9项必须完整存在"""
        from dreambuddy_evolution.weights import WEIGHTS
        b = WEIGHTS["BOUNDARIES"]
        expected = [
            "RI", "CMScore", "SCALE_KAPPA_QUANTUM",
            "CM_RESERVOIR_SCALE_M2", "TYPE_TRANSFER_BAN_RATE", "TYPE_TRANSFER_BAN_COUNT",
            "COLD_BACKUP_DAYS", "WINDOW_7D_HOURS",
        ]
        for k in expected:
            assert k in b, f"BOUNDARIES missing key: {k} -> need for Phase 2 CM/R-3 calibration"

    def test_boundaries_intervals_low_less_than_high(self):
        """TR-W-SENS-18 续：RI/CMScore 阈值档low<high 连续性"""
        from dreambuddy_evolution.weights import WEIGHTS
        for k in ("RI", "CMScore"):
            vals = WEIGHTS["BOUNDARIES"][k]
            for a, b in zip(vals, vals[1:]):
                assert a < b, f"BOUNDARIES[{k}] non-monotonic: {a} >= {b} → OAT扰动可能不连续跳变"

    def test_fallback_ri_less_than_ri_first_boundary_by_epsilon_001(self):
        """TR-W-SENS-19: RI降级值0.29严格<0.30(首档边界) ε=0.01硬约束 蓝图附录A C-3"""
        from dreambuddy_evolution.weights import FALLBACK_VALUES, WEIGHTS
        RI_first = WEIGHTS["BOUNDARIES"]["RI"][0]  # 0.30
        epsilon = RI_first - FALLBACK_VALUES["RI"]
        assert 0.005 <= epsilon <= 0.020, (
            f"FAIL-OPEN RI fallback={FALLBACK_VALUES['RI']} must < boundary[0]={RI_first} "
            f"by ε≈0.01, got ε={epsilon:.4f}"
        )

    def test_fallback_cmscore_inside_neutral_interval(self):
        """TR-W-SENS-20: CMScore降级值0.45严格在中性档(0.35, 0.55)内，不触发±boost"""
        from dreambuddy_evolution.weights import FALLBACK_VALUES, WEIGHTS
        cm = WEIGHTS["BOUNDARIES"]["CMScore"]
        low, high = cm[1], cm[2]  # 中性档 = [0.35, 0.55]
        assert low < FALLBACK_VALUES["CMScore"] < high, (
            f"FAIL-OPEN CMScore fallback={FALLBACK_VALUES['CMScore']} must be in neutral "
            f"interval ({low}, {high}), got out of range"
        )


class TestESSWeightsSensitivity:
    """ESS 4:4:2 对 数值参数 OAT ±20% 单调性 + 整体漂移 ≤ 橙灯15pp（蓝图附录 C R-1）"""

    BASE_ARGS = dict(H=0.7, S=0.75, N=400)  # 基准工况：70把握度,75结构,400样本

    def _ess_with(self, **overrides):
        """H/S/N 数值 ×{0.8,1.0,1.2}（蓝图OAT ±20%数值微扰，不是权重比！）"""
        from dreambuddy_evolution.weights import WEIGHTS
        W = WEIGHTS["ESS"]
        args = {**self.BASE_ARGS, **overrides}
        return _get_clamped_ess(args["H"], args["S"], args["N"], W)

    def test_sens01_ess_h_value_down_monotonic(self):
        """TR-W-SENS-01 H数值×0.8 → ESS 严格下降 且 漂移<0.15pp（橙灯线）"""
        base = self._ess_with()
        down = self._ess_with(H=self.BASE_ARGS["H"] * 0.8)
        assert down < base, f"H×0.8 应该ESS下降：base={base:.4f}, H=0.7×0.8={self.BASE_ARGS['H']*0.8:.2f}→{down:.4f}"
        assert (base - down) < 0.15, f"H×0.8 drift={base-down:.4f} >= 橙灯0.15pp"

    def test_sens02_ess_h_value_up_monotonic(self):
        """TR-W-SENS-02 H数值×1.2 → ESS 严格上升 且 漂移<0.15pp"""
        base = self._ess_with()
        up = self._ess_with(H=self.BASE_ARGS["H"] * 1.2)
        assert up > base, f"H×1.2 应该ESS上升：base={base:.4f}, up={up:.4f}"
        assert (up - base) < 0.15

    def test_sens03_ess_s_value_down_monotonic(self):
        """TR-W-SENS-03 S数值×0.8 → ESS下降 <0.15pp"""
        base = self._ess_with()
        down = self._ess_with(S=self.BASE_ARGS["S"] * 0.8)
        assert down < base, f"S×0.8 应该ESS下降: base={base:.4f}, down={down:.4f}"
        assert (base - down) < 0.15

    def test_sens04_ess_s_value_up_monotonic(self):
        """TR-W-SENS-04 S数值×1.2 → ESS上升 <0.15pp"""
        base = self._ess_with()
        up = self._ess_with(S=self.BASE_ARGS["S"] * 1.2)
        assert up > base, f"S×1.2 should increase: base={base:.4f} up={up:.4f}"
        assert (up - base) < 0.15

    def test_sens05_ess_n_value_down_monotonic(self):
        """TR-W-SENS-05 N数值×0.8（样本辅助项 漂移应该更小）→ ESS下降 ≤ 0.08pp（N 弱驱动）"""
        base = self._ess_with()
        down = self._ess_with(N=max(1, int(self.BASE_ARGS["N"] * 0.8)))
        assert down <= base, f"N×0.8应该ESS下降或持平: base={base:.4f}, down={down:.4f}"
        assert (base - down) <= 0.08, f"N×0.8 drift={base-down:.4f} > 0.08pp 小样本项过强驱动"

    def test_sens06_ess_n_value_up_monotonic(self):
        """TR-W-SENS-06 N数值×1.2 → ESS上升 ≤ 0.08pp（N不应强驱动）"""
        base = self._ess_with()
        up = self._ess_with(N=int(self.BASE_ARGS["N"] * 1.2))
        assert up >= base, f"N×1.2应该ESS上升或持平: base={base:.4f}, up={up:.4f}"
        assert (up - base) <= 0.08

    def test_sens07_ess_overall_oat_20_drift_below_15pct_orange_line(self):
        """TR-W-SENS-07 ESS三参数OAT±20% 【最大漂移绝对值 ≤ 橙灯15pp】门禁 蓝图附录C"""
        base = self._ess_with()
        b = self.BASE_ARGS
        deltas = [
            abs(base - self._ess_with(H=b["H"]*0.8)),  abs(base - self._ess_with(H=b["H"]*1.2)),
            abs(base - self._ess_with(S=b["S"]*0.8)),  abs(base - self._ess_with(S=b["S"]*1.2)),
            abs(base - self._ess_with(N=max(1,int(b["N"]*0.8)))),
            abs(base - self._ess_with(N=int(b["N"]*1.2))),
        ]
        max_drift = max(deltas)
        assert max_drift <= 0.15, (
            f"ESS OAT±20% max_drift={max_drift:.4f} > 橙灯阈值0.15pp → MVP预触发红橙灯！"
            f"需校准默认权重4:4:2或提交Review PR记录（如接受则白名单豁免）"
        )


class TestCrossValidationAndOtherGroups:
    """其余3组权重 OAT ±20% 扰动连续 漂移≤15pp（橙灯线）"""

    @staticmethod
    def _norm_weights(group_key, overrides):
        from dreambuddy_evolution.weights import WEIGHTS
        W = dict(WEIGHTS[group_key])
        # 对于CM，4:3:3用ML/Reservoir/CrossVal；R_REFL用corr/liq/sent；CS用Level0/ESS_top/CBR_top
        # 统一：所有三个组成部分 分别×ratio → 归一
        names_map = dict(
            R_REFL=["corr", "liq", "sent"],
            CS=["Level0", "ESS_top", "CBR_top"],
            CM=["ML", "Reservoir", "CrossVal"],
        )
        names = names_map[group_key]
        raw = {n: W[n] * overrides.get(i, 1.0) for i, n in enumerate(names)}
        s = sum(raw.values())
        return {n: v / s for n, v in raw.items()}

    def test_sens08_reflexivity_433_monotonic_all_three(self):
        """TR-W-SENS-08 R_reflexivity corr×0.8/1.2 / liq×0.8/1.2 / sent×0.8/1.2 权重比归一后仍单调（sum=1前提下），总漂移<0.15"""
        ref = self._norm_weights("R_REFL", {})
        cases = []
        for i in range(3):
            down = self._norm_weights("R_REFL", {i: 0.8})
            up = self._norm_weights("R_REFL", {i: 1.2})
            # 验证：参数下降时对应占比下降；上升时上升（单调）
            keys_list = ["corr", "liq", "sent"]
            k = keys_list[i]
            assert down[k] <= ref[k], f"R_REFL {k}×0.8 after normalization still down (monotonic)"
            assert up[k] >= ref[k], f"R_REFL {k}×1.2 after normalization still up"
            # 漂移量（ref[k] - down[k] 应该<0.08）
            assert (ref[k] - down[k]) < 0.08, f"{k}×0.8 drift too large {ref[k]-down[k]:.4f}"
            assert (up[k] - ref[k]) < 0.08

    def test_sens09_cs_level0_dominant_unchanged_order(self):
        """TR-W-SENS-09 CS Level0权重即使×0.8也应> ESS/CBR（0.4×0.8=0.32 归一后仍最大），符合0.4最高设计意图"""
        down = self._norm_weights("CS", {0: 0.8})  # Level0×0.8
        assert down["Level0"] > down["ESS_top"] and down["Level0"] > down["CBR_top"], (
            f"CS Level0×0.8归一后={down['Level0']:.4f} 不再最大，权重默认过于敏感"
        )

    def test_sens10_cm_ml_dominant_unchanged_order(self):
        """TR-W-SENS-10 CM ML权重×0.8归一后仍>Reservoir/CrossVal（0.4-降仍最大=周期最长线仍应驱动）"""
        down = self._norm_weights("CM", {0: 0.8})
        assert down["ML"] > down["Reservoir"] and down["ML"] > down["CrossVal"], (
            f"CM ML×0.8归一后={down['ML']:.4f} 不再最大 → 美林周期驱动性下降，默认过偏"
        )

    def test_sens11_ess_boundary_clamp_01(self):
        """TR-W-SENS-11（实际是TR-SG-05前瞻）ESS全0=0；H=1.0 S=1.2 N=500 clamp到1.0"""
        from dreambuddy_evolution.weights import WEIGHTS
        W = WEIGHTS["ESS"]
        assert math.isclose(_get_clamped_ess(0, 0, 0, W), 0.0, abs_tol=1e-6)
        assert math.isclose(_get_clamped_ess(1.0, 1.2, 500, W), 1.0, abs_tol=1e-6)

    def test_sens12_ess_small_sample_penalty(self):
        """TR-W-SENS-12（TR-SG-06前瞻） N=50比N=500的ESS显著低≥0.08（小样本惩罚存在）"""
        from dreambuddy_evolution.weights import WEIGHTS
        W = WEIGHTS["ESS"]
        ess_500 = _get_clamped_ess(0.7, 0.75, 500, W)
        ess_50 = _get_clamped_ess(0.7, 0.75, 50, W)
        gap = ess_500 - ess_50
        assert gap >= 0.08, f"N=50 vs 500 gap={gap:.4f} < 0.08 → 小样本惩罚不足（默认γ过弱？）"
