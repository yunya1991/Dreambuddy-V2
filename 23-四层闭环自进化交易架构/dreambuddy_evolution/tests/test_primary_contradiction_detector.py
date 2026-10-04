"""
T10d: PrimaryContradictionDetector TDD 测试
SPEC-美国宏观事件驱动交易策略.md §4.5.1

核心创新: 主要矛盾识别器 — 识别当前事件驱动阶段的主要矛盾类型、强度、周期阶段
4 种主要矛盾: fomc_rate_decision / inflation_shock / credit_event / ai_capex_cycle

HC: 异常必须 FAIL-OPEN，返回 neutral 兜底
HC: 模块化开关 enable_primary_contradiction_detector 关断时返回中性默认
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=False)
def enable_detector(monkeypatch):
    """启用主要矛盾识别器开关（非开关测试用）"""
    from dreambuddy_evolution.agi_config import set_switch, reset_switches
    reset_switches()
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_primary_contradiction_detector", True)
    yield
    reset_switches()


class TestPrimaryContradictionDetector:
    """主要矛盾识别器单元测试 (T10d)"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
            ContradictionInfo,
        )
        assert PrimaryContradictionDetector is not None
        assert ContradictionInfo is not None

    def test_detect_in_fomc_cycle_returns_fomc_contradiction(self, enable_detector):
        """FOMC 周期内 + 加息概率高 → primary=fomc_rate_decision"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
                "days_to_fomc": 10,
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision"
        assert 0.0 <= result.intensity <= 0.95
        assert result.cycle_phase == "expectation_jump"
        assert result.probability == 0.85
        assert result.probability_trend == "rising"
        assert "gold" in result.affected_assets

    def test_detect_inflation_shock_when_cpi_surprise(self, enable_detector):
        """CPI 大超预期 → primary=inflation_shock"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "cpi_actual": 5.2,
            "cpi_expected": 4.0,
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "neutral",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "inflation_shock"
        assert result.intensity > 0.3  # CPI 超预期应有强度

    def test_detect_credit_event_when_credit_contraction(self, enable_detector):
        """信贷收缩 → primary=credit_event"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "credit_growth": -2.0,  # 信贷负增长
            "gdp_growth": 1.5,
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "neutral",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "credit_event"
        assert "btc" in result.affected_assets

    def test_detect_ai_capex_cycle_when_semiconductor_boom(self, enable_detector):
        """AI 资本开支周期 + 半导体景气 → primary=ai_capex_cycle"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "ai_cycle_score": 0.85,
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "neutral",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "ai_capex_cycle"
        assert "semiconductors" in result.affected_assets

    def test_intensity_formula(self, enable_detector):
        """intensity = min(fomc_prob*0.6 + abs(prob_trend_value)*0.4, 0.95)"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        # fomc_prob=0.85, prob_trend=rising (映射为 0.3)
        # intensity = min(0.85*0.6 + 0.3*0.4, 0.95) = min(0.51 + 0.12, 0.95) = 0.63
        kline_data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
            },
        }
        result = detector.detect(kline_data)
        assert 0.60 <= result.intensity <= 0.66  # 允许实现细节差异

    def test_neutral_when_no_fomc_and_no_macro_signals(self, enable_detector):
        """无 FOMC 信号且无宏观异常 → primary=unknown, intensity=0.0"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {"event_context": {"in_fomc_cycle": False, "cycle_phase": "neutral"}}
        result = detector.detect(kline_data)
        assert result.primary == "unknown"
        assert result.intensity == 0.0
        assert result.cycle_phase == "neutral"

    def test_fail_open_on_exception(self, enable_detector):
        """HC: 数据异常时 FAIL-OPEN 返回中性默认"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        # 传入非法数据
        result = detector.detect(None)
        assert result.primary == "unknown"
        assert result.intensity == 0.0

    def test_switch_off_returns_neutral(self):
        """HC: 开关关断时返回中性默认，字节等价'模块不存在'"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)
        set_switch("enable_primary_contradiction_detector", False)
        detector = PrimaryContradictionDetector()
        kline_data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
            },
        }
        result = detector.detect(kline_data)
        # 开关关断 → 中性默认
        assert result.primary == "unknown"
        assert result.intensity == 0.0

    def test_switch_on_activates_detection(self):
        """开关启用时正常识别"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", True)
        set_switch("enable_primary_contradiction_detector", True)
        detector = PrimaryContradictionDetector()
        kline_data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision"
        assert result.intensity > 0.0

    def test_secondary_contradictions(self, enable_detector):
        """次要矛盾列表正确"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
            },
            "cpi_actual": 5.0,
            "cpi_expected": 4.0,  # 同时CPI超预期 → 次要矛盾
        }
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision"
        assert "inflation_shock" in result.secondary

    def test_to_dict_serializable(self, enable_detector):
        """ContradictionInfo 可序列化"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        result = detector.detect({"event_context": {"in_fomc_cycle": False}})
        d = result.to_dict()
        assert "primary" in d
        assert "intensity" in d
        assert "cycle_phase" in d
        assert "affected_assets" in d
        assert "secondary" in d


# ============================================================================
# T5 P0 盲区修复：解除 PrimaryContradictionDetector in_fomc 硬限制（SPEC §3.2.2）
# 非农/CPI/PPI 虽不在 FOMC 议息周期，但实质影响加息预期 → primary=fomc_rate_decision
# CESI ≥ ±1.5σ + event_type in (nfp/cpi/ppi) → 触发 macro_rate_triggered
# CESI 放大 intensity: cesi_amplifier = min(|cesi|/3.0, 0.3)
# ============================================================================


class TestPrimaryContradictionDetectorP0T5:
    """T5 P0 盲区修复 — 解除 in_fomc 硬限制。"""

    def test_not_in_fomc_but_cesi_trigger_returns_fomc_rate_decision(self, enable_detector):
        """非 FOMC + CESI=2.0 + event_type='cpi' + hike_prob=0.85 → primary=fomc_rate_decision。"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "cesi": 2.0,  # 强于 1.5σ
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
                "event_type": "cpi",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision", (
            f"CESI 触发应识别为 fomc_rate_decision，但返回 primary={result.primary}"
        )

    def test_not_in_fomc_but_negative_cesi_trigger_returns_fomc_rate_decision(self, enable_detector):
        """非 FOMC + CESI=-1.8 + event_type='nfp' + hike_prob=0.6 → primary=fomc_rate_decision。"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "cesi": -1.8,  # 负向强超预期
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.60,
                "probability_trend": "falling",
                "event_type": "nfp",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision", (
            f"负向 CESI 触发应识别为 fomc_rate_decision，但返回 primary={result.primary}"
        )

    def test_not_in_fomc_but_ppi_event_type_with_cesi_returns_fomc_rate_decision(self, enable_detector):
        """非 FOMC + CESI=1.6 + event_type='ppi' + hike_prob=0.5 → primary=fomc_rate_decision。"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "cesi": 1.6,  # 略高于 1.5σ
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.50,
                "probability_trend": "stable",
                "event_type": "ppi",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision"

    def test_not_in_fomc_cesi_below_threshold_returns_unknown_or_other(self, enable_detector):
        """非 FOMC + CESI=0.8（未达 1.5σ）+ event_type='cpi' → 不应识别为 fomc_rate_decision（CESI 触发未激活）。"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "cesi": 0.8,  # 弱于 1.5σ
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "neutral",
                "hike_prob": 0.50,
                "event_type": "cpi",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary != "fomc_rate_decision", (
            f"CESI 未达阈值不应识别为 fomc_rate_decision，但返回 primary={result.primary}"
        )

    def test_not_in_fomc_cesi_trigger_but_unknown_event_type_returns_unknown(self, enable_detector):
        """非 FOMC + CESI=2.0 + event_type='unknown'（非 nfp/cpi/ppi）→ 不应识别为 fomc_rate_decision。"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "cesi": 2.0,
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "neutral",
                "hike_prob": 0.50,
                "event_type": "unknown",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary != "fomc_rate_decision"

    def test_cesi_amplifies_intensity_beyond_baseline(self, enable_detector):
        """CESI 放大 intensity：相同 hike_prob/prob_trend 下，CESI=2.0 的 intensity 应高于 CESI=0 的。

        基线（in_fomc=True, hike_prob=0.85, prob_trend=rising, cesi=None）：
            intensity = min(0.85*0.6 + 0.3*0.4, 0.95) = min(0.51 + 0.12, 0.95) = 0.63
        CESI=2.0 时：
            cesi_amplifier = min(2.0/3.0, 0.3) = 0.333
            intensity = min(0.63 + 0.333, 0.95) = 0.963 → 截断为 0.95
        所以 CESI=2.0 时 intensity 至少应比 baseline 高。
        """
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        # baseline：FOMC 周期内，无 CESI
        baseline_kd = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
                "event_type": "fomc",
            },
        }
        baseline = detector.detect(baseline_kd)

        # CESI 放大：FOMC 周期内 + CESI=2.0
        cesi_kd = {
            "cesi": 2.0,
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
                "event_type": "cpi",
            },
        }
        cesi_result = detector.detect(cesi_kd)

        assert cesi_result.intensity > baseline.intensity, (
            f"CESI 应放大 intensity: baseline={baseline.intensity}, cesi={cesi_result.intensity}"
        )

    def test_cesi_threshold_boundary_at_exactly_1_5(self, enable_detector):
        """CESI 恰好 1.5σ 应触发（边界值，>= 阈值）。"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )
        detector = PrimaryContradictionDetector()
        kline_data = {
            "cesi": 1.5,  # 恰好 1.5σ
            "event_context": {
                "in_fomc_cycle": False,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.50,
                "probability_trend": "stable",
                "event_type": "cpi",
            },
        }
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision"
