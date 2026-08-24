"""
Task 1.2 RED：phase_c_constants.py §二 冻结硬编码常量值精确断言
------------------------------------------------------------
TDD Red-Green-Refactor Cycle 1：
  RED：本文件所有 assert 都应该 FAIL（因为 phase_c_constants.py 还没写/值不对）
  GREEN：写 phase_c_constants.py 精确匹配 §二 Spec 冻结值
  REFACTOR：无（常量文件，无逻辑可重构）
"""

import sys
import os
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR.parent))  # 11-易经推理系统/

import math
import pytest


# ============================================================
# §二 Spec v3.0 冻结硬编码常量（非 * 参数，精确值）
# ============================================================
_EXPECTED_P5 = 90.0          # P5：基线权重时间衰减半衰 90 天
_EXPECTED_P6 = 5             # P6：BCRMContinuityObserver 滚动窗口 N=5 笔
_EXPECTED_P7_CONT = 0.60     # P7：Score_B 公式的连续性分权重 60%（单笔 40%）
_EXPECTED_P7_CONF = 0.40
_EXPECTED_P8_S_BCRM = 0.50   # P8：S 构成 50% 全局 S_BCRM + 50% 连续 S_cont
_EXPECTED_P8_S_CONT = 0.50
_EXPECTED_P10_PENALTY_UP = 0.40  # P10：λ 惩罚上限 40%（clip [0.60, 1.0]）
_EXPECTED_P10_LAMBDA_LOW = 0.60
_EXPECTED_P10_LAMBDA_HIGH = 1.0
_EXPECTED_P13_G04_DD_THRESHOLD = 0.03  # P13：G-04 单日 3% 终极熔断（小数=0.03）
_EXPECTED_P16_HIGH_WIN = 100  # P16：CBR 经典战例库各 100 条，合计 200
_EXPECTED_P16_HIGH_LOSS = 100
_EXPECTED_P17_G2_N = 30       # P17：WinProb 样本门槛 30 + Brier 0.25
_EXPECTED_P17_BRIER = 0.25
_EXPECTED_F1_FLOOR = 0.05    # F1 永不 BLOCK 的底仓 = 5%
_EXPECTED_F2_CAP_DEFAULT = 0.10  # F2 P1 BLOCK 顶 = 10%
_EXPECTED_F3_SEVERE_MULT = 0.70  # F3 DIVERGE_SEVERE × 0.70
_EXPECTED_F4_BASELINE_BONUS = 1.20  # F4 基线命中 ×1.20
_EXPECTED_FINAL_CLIP_LOW = 0.05     # 全局 clip 下界
_EXPECTED_FINAL_CLIP_HIGH_DEFAULT = 1.50  # 全局 clip 上界（P15* 默认）

# fail-open 默认值（§四.1.3 / §五.1 / etc.）
_EXPECTED_FAILOPEN_WP = 0.45
_EXPECTED_FAILOPEN_WE = 0.30
_EXPECTED_FAILOPEN_WB = 0.25
_EXPECTED_FAILOPEN_ELASTIC = 0.10
_EXPECTED_FAILOPEN_LAMBDA = 1.0
_EXPECTED_FAILOPEN_WINPROB = 1.0
_EXPECTED_FAILOPEN_ELDER_GRADE = "NEUTRAL"
_EXPECTED_FAILOPEN_ELDER_SCORE = 0.65
_EXPECTED_FAILOPEN_CONT_GRADE = "NEUTRAL"
_EXPECTED_FAILOPEN_CONT_SCORE = 0.65
_EXPECTED_FAILOPEN_S_BTC_ONLY_LOW_SAMPLE = 0.50  # 样本<5 → 中性，不够 0.60 门槛


class TestPhaseCConstantsV3Frozen:
    """
    §二 冻结硬编码常量（非 * 参数，不允许修改，除非用户再次 Spec 评审）。
    所有值必须与 Spec §二 表格逐字相等。
    """

    # --------------------------------------------------------
    # RED 阶段：phase_c_constants.py 模块不存在 → ImportError
    # --------------------------------------------------------
    def test_module_importable(self):
        """RED：应该 ImportError（模块还没写）；GREEN：import 成功"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C is not None

    # --------------------------------------------------------
    # §二 冻结值精确断言（P5/P6/P7/P8/P10/P13/P16/P17）
    # --------------------------------------------------------
    def test_p5_decay_half_life_exact(self):
        """P5：基线权重时间衰减半衰 = 90.0 天（硬编码，不允许配置）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.BASELINE_DECAY_HALF_LIFE_DAYS == pytest.approx(_EXPECTED_P5, abs=1e-9)
        # 额外验证 90 天半衰 = exp(-90/90) = exp(-1) ≈ 0.3679
        assert math.exp(-90.0 / C.BASELINE_DECAY_HALF_LIFE_DAYS) == pytest.approx(math.exp(-1), abs=1e-9)

    def test_p6_continuity_window_exact(self):
        """P6：BCRMContinuityObserver 滚动窗口 = 5 笔（与 Elder 五级对齐）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert int(C.BCRM_CONTINUITY_WINDOW_N) == _EXPECTED_P6

    def test_p7_score_b_weight_ratio_exact(self):
        """P7：Score_B 公式 continuity:confidence = 60% : 40%（连续信号权重大于单笔）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.SCORE_B_CONT_WEIGHT == pytest.approx(_EXPECTED_P7_CONT, abs=1e-9)
        assert C.SCORE_B_CONF_WEIGHT == pytest.approx(_EXPECTED_P7_CONF, abs=1e-9)
        assert C.SCORE_B_CONT_WEIGHT + C.SCORE_B_CONF_WEIGHT == pytest.approx(1.0, abs=1e-9)

    def test_p8_s_global_50_50_exact(self):
        """P8：S（三层权重的胜率）= 50% S_BCRM + 50% S_cont"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.S_GLOBAL_S_BCRM_WEIGHT == pytest.approx(_EXPECTED_P8_S_BCRM, abs=1e-9)
        assert C.S_GLOBAL_S_CONT_WEIGHT == pytest.approx(_EXPECTED_P8_S_CONT, abs=1e-9)
        assert C.S_GLOBAL_S_BCRM_WEIGHT + C.S_GLOBAL_S_CONT_WEIGHT == pytest.approx(1.0, abs=1e-9)

    def test_p10_lambda_penalty_bounds_exact(self):
        """P10：λ 惩罚上限 0.40 → clip ∈ [0.60, 1.0]"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.BTC_REFLEX_PENALTY_MAX == pytest.approx(_EXPECTED_P10_PENALTY_UP, abs=1e-9)
        assert C.BTC_REFLEX_LAMBDA_LOW == pytest.approx(_EXPECTED_P10_LAMBDA_LOW, abs=1e-9)
        assert C.BTC_REFLEX_LAMBDA_HIGH == pytest.approx(_EXPECTED_P10_LAMBDA_HIGH, abs=1e-9)
        # 验证：1 - 0.40 = 0.60，等于 low clip
        assert (1.0 - C.BTC_REFLEX_PENALTY_MAX) == pytest.approx(C.BTC_REFLEX_LAMBDA_LOW, abs=1e-9)

    def test_p13_g04_3pct_ultimate_fuse(self):
        """P13：G-04 单日 3% 终极熔断（桥水全天候红线）= 0.03 小数"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.G04_DAILY_DRAWDOWN_THRESHOLD == pytest.approx(_EXPECTED_P13_G04_DD_THRESHOLD, abs=1e-9)
        # 语义：prev=1000, curr=970 → 3.0% 回撤刚好触发
        assert (1000 - 970) / 1000 == pytest.approx(C.G04_DAILY_DRAWDOWN_THRESHOLD, abs=1e-9)

    def test_p16_cbr_classic_case_library_size(self):
        """P16：CBR 经典战例库 HIGH_WIN 100 条 + HIGH_LOSS 100 条 = 合计 200 条"""
        from scripts.memory_l4 import phase_c_constants as C
        assert int(C.CBR_LIBRARY_HIGH_WIN) == _EXPECTED_P16_HIGH_WIN
        assert int(C.CBR_LIBRARY_HIGH_LOSS) == _EXPECTED_P16_HIGH_LOSS
        assert int(C.CBR_LIBRARY_TOTAL) == _EXPECTED_P16_HIGH_WIN + _EXPECTED_P16_HIGH_LOSS

    def test_p17_winprob_gating_thresholds(self):
        """P17：WinProb 样本门槛 30 条 + Brier ≤ 0.25"""
        from scripts.memory_l4 import phase_c_constants as C
        assert int(C.WINPROB_G2_MIN_SAMPLES) == _EXPECTED_P17_G2_N
        assert C.WINPROB_G3_MAX_BRIER == pytest.approx(_EXPECTED_P17_BRIER, abs=1e-9)

    # --------------------------------------------------------
    # F1~F4 铁则 + 全局 clip 上下界（§五 5.3 + F4）
    # --------------------------------------------------------
    def test_f1_never_block_floor(self):
        """F1 永不 BLOCK：仓位底 = 5%（即使 P1=BLOCK × Elder=SEVERE 也给 5% 试错仓）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.F1_NEVER_BLOCK_FLOOR == pytest.approx(_EXPECTED_F1_FLOOR, abs=1e-9)

    def test_f2_p1_block_cap_default(self):
        """F2：P1 原始=BLOCK → final ≤ 0.10（默认，P14* 回测可替换）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.F2_P1_BLOCK_CAP_DEFAULT == pytest.approx(_EXPECTED_F2_CAP_DEFAULT, abs=1e-9)

    def test_f3_diverge_severe_discount(self):
        """F3：Elder 五级 = DIVERGE_SEVERE → × 0.70"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.F3_DIVERGE_SEVERE_MULT == pytest.approx(_EXPECTED_F3_SEVERE_MULT, abs=1e-9)

    def test_f4_baseline_family_bonus(self):
        """F4：CBR top1 家族 match ≥ θ → × 1.20"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.F4_BASELINE_BONUS_MULT == pytest.approx(_EXPECTED_F4_BASELINE_BONUS, abs=1e-9)

    def test_global_final_position_clip_bounds(self):
        """全局 final_pos_mult clip：[0.05, 1.50]（P15* 默认）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FINAL_POS_MULT_CLIP_LOW == pytest.approx(_EXPECTED_FINAL_CLIP_LOW, abs=1e-9)
        assert C.FINAL_POS_MULT_CLIP_HIGH_DEFAULT == pytest.approx(_EXPECTED_FINAL_CLIP_HIGH_DEFAULT, abs=1e-9)

    # --------------------------------------------------------
    # Fail-open 常量对齐：L2~L6 降级值（§十 10.2）
    # --------------------------------------------------------
    def test_failopen_cold_start_weights_exact(self):
        """L2 fail-open：冷启动权重 45:30:25"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FAILOPEN_WP == pytest.approx(_EXPECTED_FAILOPEN_WP, abs=1e-9)
        assert C.FAILOPEN_WE == pytest.approx(_EXPECTED_FAILOPEN_WE, abs=1e-9)
        assert C.FAILOPEN_WB == pytest.approx(_EXPECTED_FAILOPEN_WB, abs=1e-9)
        assert C.FAILOPEN_WP + C.FAILOPEN_WE + C.FAILOPEN_WB == pytest.approx(1.0, abs=1e-9)

    def test_failopen_elastic_gate_3l(self):
        """L3 fail-open：ElasticGate3L Score 异常 → 0.10"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FAILOPEN_ELASTIC_MULT == pytest.approx(_EXPECTED_FAILOPEN_ELASTIC, abs=1e-9)

    def test_failopen_btc_reflex_lambda(self):
        """L4 fail-open：BTC 自反闸门异常 → λ=1.0（零影响）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FAILOPEN_BTC_REFLEX_LAMBDA == pytest.approx(_EXPECTED_FAILOPEN_LAMBDA, abs=1e-9)

    def test_failopen_winprob_multiplier(self):
        """L5 fail-open：WinProb 异常 → 1.0（零影响）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FAILOPEN_WINPROB_MULT == pytest.approx(_EXPECTED_FAILOPEN_WINPROB, abs=1e-9)

    def test_failopen_elder_grade_neutral(self):
        """Elder-ray fail-open：NEUTRAL 档位 0.65（字节等价零影响）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FAILOPEN_ELDER_GRADE == _EXPECTED_FAILOPEN_ELDER_GRADE
        assert C.FAILOPEN_ELDER_SCORE == pytest.approx(_EXPECTED_FAILOPEN_ELDER_SCORE, abs=1e-9)

    def test_failopen_bcrm_continuity_neutral(self):
        """BCRMContinuityObserver fail-open：NEUTRAL 档位 0.65（Score_B 退化为纯 conf 线性 0.40×）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FAILOPEN_CONT_GRADE == _EXPECTED_FAILOPEN_CONT_GRADE
        assert C.FAILOPEN_CONT_SCORE == pytest.approx(_EXPECTED_FAILOPEN_CONT_SCORE, abs=1e-9)
        # 退化语义：SW-C7=False → Score_B = 0.60×0.65 + 0.40×conf = 0.39 + 0.40×conf
        # 纯 v2.0 Score_B 全 = 1.0×pure_conf_linear，差异很小但独立（正交隔离）
        assert C.FAILOPEN_CONT_SCORE * C.SCORE_B_CONT_WEIGHT == pytest.approx(0.39, abs=1e-9)

    def test_failopen_s_btc_only_small_sample_neutral(self):
        """BTC 专属胜率样本<5 → 0.50 中性，P9 门槛 ≥0.60 自动不满足（防小数定律自激）"""
        from scripts.memory_l4 import phase_c_constants as C
        assert C.FAILOPEN_S_BTC_ONLY_LOW_SAMPLE == pytest.approx(
            _EXPECTED_FAILOPEN_S_BTC_ONLY_LOW_SAMPLE, abs=1e-9
        )
        assert C.FAILOPEN_S_BTC_ONLY_LOW_SAMPLE < 0.60, (
            "FAILOPEN 中性 0.50 必须严格小于 BTC 自反门槛 0.60，"
            "保证冷启动样本不足时绝不触发惩罚。"
        )
