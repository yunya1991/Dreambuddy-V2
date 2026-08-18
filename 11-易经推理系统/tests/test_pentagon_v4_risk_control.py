"""五角校验 v4 风险评分风控版 单元测试

覆盖范围：
  1. PentagonParams 默认值与边界
  2. TriangleVerificationResult 字段完整性
  3. 五源风险信号提取
  4. 风险评分计算（等权场景）
  5. 风险评分分档（LOW/NORMAL/MID/HIGH）
  6. 双向风控调控（仓位/杠杆/止盈/止损）
  7. v3 双预警止损收紧底线叠加
  8. 不干预项（方向投票/置信度/开仓阻断）
  9. record_outcome 风险注意力更新
  10. 风险注意力权重边界与衰减
"""
import sys
import os
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ============================================================
# inspect 遮蔽修复（memory_l4/inspect.py 会遮蔽标准库）
# 必须在 import triangle_verifier 之前执行
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
MEMORY_L4_DIR = SCRIPTS_DIR / "memory_l4"

# 临时移除 memory_l4 路径，确保标准库 inspect 先加载
_remove_paths = [str(p) for p in sys.path if "memory_l4" in p or p == str(MEMORY_L4_DIR)]
for _p in _remove_paths:
    if _p in sys.path:
        sys.path.remove(_p)

# 强制加载标准库 inspect
_std_inspect = importlib.import_module("inspect")
sys.modules["inspect"] = _std_inspect

# 恢复路径
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(MEMORY_L4_DIR))

# 现在 safe import triangle_verifier
from scripts.memory_l4.triangle_verifier import (
    PentagonParams,
    TriangleVerificationResult,
    TriangleVerifier,
)


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def default_params():
    """默认 v4 参数"""
    return PentagonParams()


@pytest.fixture
def verifier():
    """默认 TriangleVerifier 实例（检测器未初始化，返回中性值）"""
    return TriangleVerifier()


@pytest.fixture
def verifier_mocked(monkeypatch):
    """检测器全部 mock 的 TriangleVerifier，可通过属性控制风险信号"""
    v = TriangleVerifier()
    # 默认：无反转、无预警
    v._mock_force_reversal = False
    v._mock_force_strength = 0.0
    v._mock_ising_alert = False
    v._mock_ising_phase = "UNKNOWN"
    v._mock_tda_warning = False
    v._mock_tda_strength = 0.0

    monkeypatch.setattr(v, "_run_force_engine", lambda snap, df=None: (
        0, v._mock_force_reversal, v._mock_force_strength, {}
    ))
    monkeypatch.setattr(v, "_run_ising_detector", lambda snap, df=None: (
        0, v._mock_ising_alert, v._mock_ising_phase, {}
    ))
    monkeypatch.setattr(v, "_run_tda_detector", lambda snap, df=None: (
        0, v._mock_tda_warning, v._mock_tda_strength, {}
    ))
    return v


def make_a0_result(tension=0.0, trauma=False):
    """构造 A0 结果字典"""
    return {"overall_tension": tension, "trauma_signal": trauma, "direction_bias": 0.0}


# ============================================================
# 1. PentagonParams 默认值与边界
# ============================================================
class TestPentagonParams:
    """验证 v4 参数默认值"""

    def test_v3_double_warning_retained(self, default_params):
        """v3 双预警止损收紧底线保留"""
        assert default_params.sl_tighten_double == 0.85
        assert default_params.sl_tighten_single == 1.0

    def test_risk_thresholds(self, default_params):
        """风险评分分档阈值"""
        assert default_params.risk_threshold_low == 0.15
        assert default_params.risk_threshold_mid == 0.50
        assert default_params.risk_threshold_high == 0.70

    def test_low_risk_factors(self, default_params):
        """低风险档：温和加仓/提杠杆/提高止盈"""
        assert default_params.pos_factor_low_risk == 1.10
        assert default_params.leverage_factor_low_risk == 1.05
        assert default_params.tp_mult_low_risk == 1.10

    def test_normal_factors(self, default_params):
        """正常档：不调整"""
        assert default_params.pos_factor_normal == 1.0
        assert default_params.leverage_factor_normal == 1.0
        assert default_params.tp_mult_normal == 1.0

    def test_mid_risk_factors(self, default_params):
        """中风险档：降仓/降杠杆/略降止盈/略收紧止损"""
        assert default_params.pos_factor_mid_risk == 0.85
        assert default_params.leverage_factor_mid_risk == 0.90
        assert default_params.tp_mult_mid_risk == 0.95
        assert default_params.sl_tighten_mid_risk == 0.95

    def test_high_risk_factors(self, default_params):
        """高风险档：大幅降仓/降杠杆/降止盈/收紧止损"""
        assert default_params.pos_factor_high_risk == 0.60
        assert default_params.leverage_factor_high_risk == 0.70
        assert default_params.tp_mult_high_risk == 0.90
        assert default_params.sl_tighten_high_risk == 0.85

    def test_risk_attention_params(self, default_params):
        """风险注意力参数"""
        assert default_params.risk_attention_enabled is True
        assert default_params.risk_attention_window == 30
        assert default_params.risk_attention_decay == 0.97
        assert default_params.risk_attention_min_weight == 0.10
        assert default_params.risk_attention_max_weight == 0.40

    def test_initial_risk_weights_equal(self, default_params):
        """五源初始等权 0.20"""
        assert default_params.risk_weight_bcrm2 == 0.20
        assert default_params.risk_weight_force == 0.20
        assert default_params.risk_weight_a0 == 0.20
        assert default_params.risk_weight_ising == 0.20
        assert default_params.risk_weight_tda == 0.20

    def test_v3_legacy_neutral(self, default_params):
        """v3 遗留参数全部中性"""
        assert default_params.attention_enabled is False
        assert default_params.bonus_strong_agree == 0.0
        assert default_params.penalty_double_warning == 0.0
        assert default_params.fail_closed_threshold == 0.0
        assert default_params.pos_factor_double_warning == 1.0


# ============================================================
# 2. TriangleVerificationResult 字段完整性
# ============================================================
class TestVerificationResult:
    """验证结果字段"""

    def test_v4_new_fields_exist(self):
        """v4 新增字段存在且有默认值"""
        r = TriangleVerificationResult()
        assert r.risk_score == 0.0
        assert r.risk_level == "NORMAL"
        assert r.leverage_factor == 1.0
        assert r.tp_adjustment == 1.0

    def test_v3_fields_retained(self):
        """v3 保留字段存在"""
        r = TriangleVerificationResult()
        assert r.position_factor == 1.0
        assert r.sl_tighten_factor == 1.0
        assert r.early_exit_signal is False

    def test_to_dict_includes_v4_fields(self):
        """to_dict 包含 v4 字段"""
        r = TriangleVerificationResult()
        d = r.to_dict()
        assert "risk_score" in d
        assert "risk_level" in d
        assert "leverage_factor" in d
        assert "tp_adjustment" in d
        assert "position_factor" in d
        assert "sl_tighten_factor" in d
        assert "early_exit_signal" in d


# ============================================================
# 3. 五源风险信号提取与风险评分计算
# ============================================================
class TestRiskScoreCalculation:
    """风险评分计算"""

    def test_all_safe_low_risk(self, verifier_mocked):
        """全部安全信号 → 低风险评分"""
        # bcrm2 高置信度(0.95) → bcrm2风险=0.05
        # force 无反转 → 0.2
        # a0 无tension → 0.0
        # ising 无预警 → 0.1
        # tda 无预警 → 0.1
        # 等权: (0.05+0.2+0.0+0.1+0.1)/5 = 0.09
        result = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        assert result.risk_score == pytest.approx(0.09, abs=0.01)
        assert result.risk_level == "LOW"

    def test_all_dangerous_high_risk(self, verifier_mocked):
        """全部危险信号 → 高风险评分"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        # bcrm2 低置信度(0.05) → bcrm2风险=0.95
        # force 反转 → 0.8
        # a0 tension=1.0 → 1.0
        # ising 预警 → 0.9
        # tda 预警 → 0.9
        # 等权: (0.95+0.8+1.0+0.9+0.9)/5 = 0.91
        result = verifier_mocked.verify("UP", 0.05, make_a0_result(1.0), {})
        assert result.risk_score == pytest.approx(0.91, abs=0.01)
        assert result.risk_level == "HIGH"

    def test_mixed_signals_normal(self, verifier_mocked):
        """混合信号 → 正常档"""
        # bcrm2 中等置信度(0.6) → bcrm2风险=0.4
        # force 无反转 → 0.2
        # a0 tension=0.3 → 0.3
        # ising 无预警 → 0.1
        # tda 无预警 → 0.1
        # 等权: (0.4+0.2+0.3+0.1+0.1)/5 = 0.22
        result = verifier_mocked.verify("UP", 0.6, make_a0_result(0.3), {})
        assert result.risk_score == pytest.approx(0.22, abs=0.01)
        assert result.risk_level == "NORMAL"

    def test_mixed_signals_mid(self, verifier_mocked):
        """中风险档"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        # bcrm2 置信度(0.5) → 0.5
        # force 反转 → 0.8
        # a0 tension=0.2 → 0.2
        # ising 预警 → 0.9
        # tda 无预警 → 0.1
        # 等权: (0.5+0.8+0.2+0.9+0.1)/5 = 0.50
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.2), {})
        assert result.risk_score == pytest.approx(0.50, abs=0.01)
        assert result.risk_level == "MID"

    def test_risk_score_bounded(self, verifier_mocked):
        """风险评分在 [0, 1] 范围内"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        result = verifier_mocked.verify("UP", 0.0, make_a0_result(1.0, trauma=True), {})
        assert 0.0 <= result.risk_score <= 1.0

    def test_bcrm2_confidence_inverse(self, verifier_mocked):
        """BCRM2 置信度越低 → 风险越高"""
        r_high_conf = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        r_low_conf = verifier_mocked.verify("UP", 0.20, make_a0_result(0.0), {})
        assert r_low_conf.risk_score > r_high_conf.risk_score


# ============================================================
# 4. 双向风控调控（仓位/杠杆/止盈/止损）
# ============================================================
class TestRiskControlAdjustment:
    """风险评分分档 → 风控调控"""

    def test_low_risk_position_up(self, verifier_mocked):
        """低风险 → 加仓"""
        result = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        assert result.position_factor == pytest.approx(1.10, abs=0.01)
        assert result.position_factor > 1.0

    def test_low_risk_leverage_up(self, verifier_mocked):
        """低风险 → 提杠杆"""
        result = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        assert result.leverage_factor == pytest.approx(1.05, abs=0.01)
        assert result.leverage_factor > 1.0

    def test_low_risk_tp_up(self, verifier_mocked):
        """低风险 → 提高止盈"""
        result = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        assert result.tp_adjustment == pytest.approx(1.10, abs=0.01)
        assert result.tp_adjustment > 1.0

    def test_low_risk_no_sl_tighten(self, verifier_mocked):
        """低风险 → 不收紧止损"""
        result = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        assert result.sl_tighten_factor == 1.0

    def test_normal_no_adjustment(self, verifier_mocked):
        """正常档 → 全部不调整"""
        result = verifier_mocked.verify("UP", 0.6, make_a0_result(0.3), {})
        assert result.position_factor == 1.0
        assert result.leverage_factor == 1.0
        assert result.tp_adjustment == 1.0
        assert result.sl_tighten_factor == 1.0

    def test_mid_risk_position_down(self, verifier_mocked):
        """中风险 → 降仓"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.2), {})
        assert result.position_factor == pytest.approx(0.85, abs=0.01)
        assert result.position_factor < 1.0

    def test_mid_risk_leverage_down(self, verifier_mocked):
        """中风险 → 降杠杆"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.2), {})
        assert result.leverage_factor == pytest.approx(0.90, abs=0.01)
        assert result.leverage_factor < 1.0

    def test_mid_risk_sl_tighten(self, verifier_mocked):
        """中风险 → 收紧止损"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.2), {})
        assert result.sl_tighten_factor == pytest.approx(0.95, abs=0.01)
        assert result.sl_tighten_factor < 1.0

    def test_high_risk_position_heavy_down(self, verifier_mocked):
        """高风险 → 大幅降仓"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        result = verifier_mocked.verify("UP", 0.05, make_a0_result(1.0), {})
        assert result.position_factor == pytest.approx(0.60, abs=0.01)

    def test_high_risk_leverage_heavy_down(self, verifier_mocked):
        """高风险 → 大幅降杠杆"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        result = verifier_mocked.verify("UP", 0.05, make_a0_result(1.0), {})
        assert result.leverage_factor == pytest.approx(0.70, abs=0.01)

    def test_high_risk_sl_tighten(self, verifier_mocked):
        """高风险 → 收紧止损"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        result = verifier_mocked.verify("UP", 0.05, make_a0_result(1.0), {})
        assert result.sl_tighten_factor == pytest.approx(0.85, abs=0.01)

    def test_verdict_includes_risk_level(self, verifier_mocked):
        """verdict 包含风险等级"""
        result_low = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        assert "LOW" in result_low.verdict
        assert result_low.verdict.startswith("P4_RISK_CONTROL")

        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        result_high = verifier_mocked.verify("UP", 0.05, make_a0_result(1.0), {})
        assert "HIGH" in result_high.verdict


# ============================================================
# 5. v3 双预警止损收紧底线叠加
# ============================================================
class TestDoubleWarningBottomline:
    """v3 双预警底线：TDA+Ising 同时触发 → sl_tighten=0.85"""

    def test_double_warning_sl_tighten(self, verifier_mocked):
        """双预警触发 → 止损收紧 0.85"""
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        # 即使风险评分在低档，双预警底线也应生效
        result = verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})
        assert result.sl_tighten_factor <= 0.85
        assert result.early_exit_signal is True
        assert result.reversal_alert is True

    def test_double_warning_takes_min(self, verifier_mocked):
        """双预警底线取风险评分和 0.85 的较小值"""
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        # 高风险档 sl_tighten=0.85，双预警也是 0.85 → 取 min=0.85
        result = verifier_mocked.verify("UP", 0.05, make_a0_result(1.0), {})
        assert result.sl_tighten_factor == pytest.approx(0.85, abs=0.01)

    def test_single_warning_no_early_exit(self, verifier_mocked):
        """单一预警不触发 early_exit"""
        verifier_mocked._mock_tda_warning = True
        verifier_mocked._mock_ising_alert = False
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.3), {})
        assert result.early_exit_signal is False

    def test_double_warning_reversal_strength(self, verifier_mocked):
        """双预警 → reversal_strength 基于 tda_strength"""
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        verifier_mocked._mock_tda_strength = 0.6
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
        # reversal_strength = 0.5 + tda_strength * 0.5 = 0.5 + 0.3 = 0.8
        assert result.reversal_strength == pytest.approx(0.8, abs=0.01)


# ============================================================
# 6. 不干预项（方向投票/置信度/开仓阻断）
# ============================================================
class TestNonInterference:
    """v4 不干预项验证"""

    def test_no_confidence_adjustment(self, verifier_mocked):
        """不调整置信度"""
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.5), {})
        assert result.confidence_adjustment == 0.0

    def test_no_fail_closed(self, verifier_mocked):
        """不触发开仓阻断"""
        verifier_mocked._mock_force_reversal = True
        verifier_mocked._mock_ising_alert = True
        verifier_mocked._mock_tda_warning = True
        result = verifier_mocked.verify("UP", 0.05, make_a0_result(1.0, trauma=True), {})
        assert result.should_fail_closed is False

    def test_no_direction_voting(self, verifier_mocked):
        """不参与方向投票（agreement_score 恒 0.5）"""
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.5), {})
        assert result.agreement_score == 0.5

    def test_trauma_resets_velocity(self, verifier_mocked):
        """创伤信号重置力学引擎速度（但不开仓阻断）"""
        verifier_mocked._force_engine = MagicMock()
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.5, trauma=True), {})
        verifier_mocked._force_engine.reset_velocity.assert_called_once()
        assert result.should_fail_closed is False


# ============================================================
# 7. record_outcome 风险注意力更新
# ============================================================
class TestRiskAttentionUpdate:
    """风险注意力机制测试"""

    def test_record_outcome_no_crash_without_pnl(self, verifier_mocked):
        """record_outcome 无 pnl_pct 时不崩溃（退化模式）"""
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
        verifier_mocked.record_outcome(
            source_directions={"bcrm2": 1, "force": 0, "a0": 0, "ising": 0, "tda": 0},
            actual_direction=1,
        )

    def test_record_outcome_with_pnl(self, verifier_mocked):
        """record_outcome 有 pnl_pct 时正常记录"""
        verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
        verifier_mocked.record_outcome(
            source_directions={"bcrm2": 1, "force": 0, "a0": 0, "ising": 0, "tda": 0},
            actual_direction=1,
            actual_pnl_pct=-5.0,
        )

    def test_high_risk_warning_correct_prediction(self, verifier_mocked):
        """高风险预警 + 市场恶化 → 准确，权重应增加"""
        # TDA 预警(高风险信号0.9) + 市场确实恶化(pnl<0)
        verifier_mocked._mock_tda_warning = True
        verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})

        for _ in range(5):
            verifier_mocked.record_outcome(
                source_directions={"tda": 0},
                actual_direction=1,
                actual_pnl_pct=-3.0,
            )

        stats = verifier_mocked.get_attention_stats()
        # tda 预警准确率应为 1.0，权重应增加（>0.20 初始值）
        assert stats["tda"]["accuracy"] == pytest.approx(1.0, abs=0.01)
        assert stats["tda"]["current_weight"] > 0.20

    def test_high_risk_warning_wrong_prediction(self, verifier_mocked):
        """高风险预警 + 市场没恶化 → 不准确，权重应减少"""
        verifier_mocked._mock_tda_warning = True
        verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})

        for _ in range(5):
            verifier_mocked.record_outcome(
                source_directions={"tda": 0},
                actual_direction=1,
                actual_pnl_pct=5.0,  # 市场没恶化
            )

        stats = verifier_mocked.get_attention_stats()
        # tda 预警准确率应为 0.0，权重应减少（<0.20 初始值）
        assert stats["tda"]["accuracy"] == pytest.approx(0.0, abs=0.01)
        assert stats["tda"]["current_weight"] < 0.20

    def test_low_risk_signal_correct(self, verifier_mocked):
        """低风险信号 + 市场没恶化 → 准确"""
        # 全部安全信号 + 市场上涨
        verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})

        for _ in range(5):
            verifier_mocked.record_outcome(
                source_directions={"bcrm2": 1},
                actual_direction=1,
                actual_pnl_pct=5.0,
            )

        stats = verifier_mocked.get_attention_stats()
        # bcrm2 低风险信号(risk=0.05<0.3) + 市场没恶化 → 准确
        assert stats["bcrm2"]["accuracy"] == pytest.approx(1.0, abs=0.01)

    def test_low_risk_signal_wrong(self, verifier_mocked):
        """低风险信号 + 市场恶化 → 不准确"""
        verifier_mocked.verify("UP", 0.95, make_a0_result(0.0), {})

        for _ in range(5):
            verifier_mocked.record_outcome(
                source_directions={"bcrm2": 1},
                actual_direction=1,
                actual_pnl_pct=-5.0,
            )

        stats = verifier_mocked.get_attention_stats()
        assert stats["bcrm2"]["accuracy"] == pytest.approx(0.0, abs=0.01)

    def test_weight_within_bounds(self, verifier_mocked):
        """注意力权重在 [min, max] 范围内"""
        verifier_mocked._mock_tda_warning = True
        params = verifier_mocked.params

        # 连续正确预测 20 次 → 权重应到上限
        for _ in range(20):
            verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
            verifier_mocked.record_outcome(
                source_directions={"tda": 0},
                actual_direction=1,
                actual_pnl_pct=-3.0,
            )

        stats = verifier_mocked.get_attention_stats()
        assert stats["tda"]["current_weight"] <= params.risk_attention_max_weight

    def test_weight_min_bound(self, verifier_mocked):
        """注意力权重不低于下限"""
        verifier_mocked._mock_tda_warning = True
        params = verifier_mocked.params

        # 连续错误预测 20 次 → 权重应到下限
        for _ in range(20):
            verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
            verifier_mocker = verifier_mocked
            verifier_mocker.record_outcome(
                source_directions={"tda": 0},
                actual_direction=1,
                actual_pnl_pct=5.0,
            )

        stats = verifier_mocked.get_attention_stats()
        assert stats["tda"]["current_weight"] >= params.risk_attention_min_weight

    def test_attention_disabled(self, monkeypatch):
        """风险注意力禁用时权重不变"""
        params = PentagonParams(risk_attention_enabled=False)
        v = TriangleVerifier(params)
        v._mock_tda_warning = True
        monkeypatch.setattr(v, "_run_force_engine", lambda s, df=None: (0, False, 0.0, {}))
        monkeypatch.setattr(v, "_run_ising_detector", lambda s, df=None: (0, False, "UNK", {}))
        monkeypatch.setattr(v, "_run_tda_detector", lambda s, df=None: (0, True, 0.5, {}))

        v.verify("UP", 0.5, make_a0_result(0.0), {})
        v.record_outcome(
            source_directions={"tda": 0},
            actual_direction=1,
            actual_pnl_pct=-5.0,
        )

        stats = v.get_attention_stats()
        # 禁用时权重不变
        assert stats["tda"]["current_weight"] == 0.20
        assert stats["tda"]["samples"] == 0

    def test_mid_range_no_scoring(self, verifier_mocked):
        """中间区域风险信号(0.3-0.5)不评分"""
        # bcrm2 置信度 0.7 → risk=0.3（中间区域）
        verifier_mocked.verify("UP", 0.7, make_a0_result(0.0), {})
        verifier_mocked.record_outcome(
            source_directions={"bcrm2": 1},
            actual_direction=1,
            actual_pnl_pct=-5.0,
        )
        stats = verifier_mocked.get_attention_stats()
        # bcrm2 risk=0.3 在 0.3-0.5 中间区域，不评分
        assert stats["bcrm2"]["samples"] == 0


# ============================================================
# 8. 风险注意力对风险评分的影响
# ============================================================
class TestAttentionImpactOnScore:
    """风险注意力权重变化对风险评分的影响"""

    def test_weight_change_affects_score(self, verifier_mocked):
        """权重变化后风险评分改变"""
        verifier_mocked._mock_tda_warning = True

        # 初始风险评分（等权）
        r1 = verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
        initial_score = r1.risk_score

        # TDA 连续正确预警 → 权重增加
        for _ in range(10):
            verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
            verifier_mocked.record_outcome(
                source_directions={"tda": 0},
                actual_direction=1,
                actual_pnl_pct=-3.0,
            )

        # 权重变化后的风险评分
        r2 = verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
        # TDA 权重增加，其风险信号(0.9)权重更大 → 总风险评分应升高
        assert r2.risk_score > initial_score

    def test_weights_sum_not_required(self, verifier_mocked):
        """权重不需要归一化（verify 内部归一化）"""
        # 手动设置不等权重
        verifier_mocked._risk_dynamic_weights = {
            "bcrm2": 0.40, "force": 0.10, "a0": 0.10, "ising": 0.10, "tda": 0.40
        }
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.3), {})
        # 应正常计算，不报错
        assert 0.0 <= result.risk_score <= 1.0


# ============================================================
# 9. A0 trauma 信号处理
# ============================================================
class TestTraumaSignal:
    """A0 创伤信号处理"""

    def test_trauma_increases_a0_risk(self, verifier_mocked):
        """创伤信号增加 A0 风险"""
        r_no_trauma = verifier_mocked.verify("UP", 0.5, make_a0_result(0.3, trauma=False), {})
        r_trauma = verifier_mocked.verify("UP", 0.5, make_a0_result(0.3, trauma=True), {})
        assert r_trauma.risk_score > r_no_trauma.risk_score

    def test_trauma_risk_capped_at_1(self, verifier_mocked):
        """A0 风险信号上界 1.0"""
        # tension=0.9 + trauma=0.3 → 1.2 → cap to 1.0
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.9, trauma=True), {})
        # a0 风险信号 = min(1.0, 0.9+0.3) = 1.0
        # 不直接测内部值，但风险评分应合理
        assert result.risk_score <= 1.0


# ============================================================
# 10. 空值与边界处理
# ============================================================
class TestEdgeCases:
    """边界条件"""

    def test_none_a0_result(self, verifier_mocked):
        """a0_result_dict=None 不崩溃"""
        result = verifier_mocked.verify("UP", 0.5, None, {})
        assert result.risk_score >= 0.0

    def test_empty_market_snapshot(self, verifier_mocked):
        """空 market_snapshot 不崩溃"""
        result = verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
        assert result is not None

    def test_zero_confidence(self, verifier_mocked):
        """置信度=0 → bcrm2 风险=1.0"""
        result = verifier_mocked.verify("UP", 0.0, make_a0_result(0.0), {})
        # bcrm2 风险=1.0，其他源较低（0.2+0+0.1+0.1）→ 均值 0.28
        assert result.risk_score > 0.2

    def test_max_confidence(self, verifier_mocked):
        """置信度=1.0 → bcrm2 风险=0.0"""
        result = verifier_mocked.verify("UP", 1.0, make_a0_result(0.0), {})
        # bcrm2 风险=0.0，其他源也低 → 低风险
        assert result.risk_level == "LOW"

    def test_direction_string_parsing(self, verifier_mocked):
        """方向字符串正确解析"""
        r_up = verifier_mocked.verify("UP", 0.5, make_a0_result(0.0), {})
        r_down = verifier_mocked.verify("DOWN", 0.5, make_a0_result(0.0), {})
        r_flat = verifier_mocked.verify("FLAT", 0.5, make_a0_result(0.0), {})
        assert r_up.bcrm2_direction == 1
        assert r_down.bcrm2_direction == -1
        assert r_flat.bcrm2_direction == 0
