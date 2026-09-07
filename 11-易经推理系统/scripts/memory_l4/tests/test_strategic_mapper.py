"""TC: StrategicMapper 测试。

验证力向量 → war_state/cap/mask 映射 + 矛盾转化调整 + FAIL-OPEN。
对应 Spec §四 strategic_mapper。
"""
import copy
import sys
from pathlib import Path

import pytest

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.models import (
    ContradictionTransform,
    ForceVector,
    StrategicLayerOutput,
)
from force_vector.strategic_mapper import StrategicMapper


# ============================================================
# 辅助构造函数
# ============================================================
def _make_contradiction(transform_type: str, **overrides) -> ContradictionTransform:
    """构造 ContradictionTransform。"""
    defaults = dict(
        transforming=True,
        transform_type=transform_type,
        trigger_conditions=["c1"],
        confidence=0.8,
        monitoring_points=["m1"],
        data_quality_factor=1.0,
    )
    defaults.update(overrides)
    return ContradictionTransform(**defaults)


def _make_force_vectors(confidence: float = 0.9) -> dict:
    """构造单维力向量字典。"""
    fv = ForceVector(
        dimension="dao",
        direction=0.5,
        magnitude=0.6,
        confidence=confidence,
        velocity=0.0,
        acceleration=0.0,
        kalman_direction=0.5,
        kalman_magnitude=0.6,
        dominant=True,
        weight=0.2,
    )
    return {"dao": fv}


# ============================================================
# TC15: elasticity_decay 触发
# ============================================================
class TestElasticityDecayTransform:
    """TC15: elasticity_decay → cap×0.5, 禁 trend_follow, war_state=COOLDOWN。"""

    def test_elasticity_decay_caps_state_and_mask(self):
        mapper = StrategicMapper()
        contradiction = _make_contradiction("elasticity_decay")
        result = mapper.map(
            final_direction=0.5,
            final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=contradiction,
            enable_force_vector=False,
        )
        assert isinstance(result, StrategicLayerOutput)
        # war_state 被强制为 COOLDOWN
        assert result.war_state == "COOLDOWN"
        # cap 被基准 ×0.5，应低于 0.5 * 1.0
        assert result.aggregate_position_cap_pct < 0.5 * 1.0
        # trend_follow / breakout 被禁
        assert result.allowed_style_mask["trend_follow"] is False
        assert result.allowed_style_mask["breakout"] is False


# ============================================================
# 额外测试 1: 无矛盾 + resonance + direction>0
# ============================================================
class TestBaseMappingNoContradiction:
    """基准映射（无矛盾转化）。"""

    def test_resonance_bullish_allows_full_cap(self):
        """resonance + direction>0 → ALLOW, cap∈[0.5,1.0], trend_follow=True。"""
        mapper = StrategicMapper()
        result = mapper.map(
            final_direction=0.5,
            final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=None,
            enable_force_vector=False,
        )
        assert result.war_state == "ALLOW"
        assert 0.5 <= result.aggregate_position_cap_pct <= 1.0
        assert result.allowed_style_mask["trend_follow"] is True

    def test_divergence_freezes_minimal_cap(self):
        """divergence → FREEZE, cap∈[0.1,0.2], 仅 emergency。"""
        mapper = StrategicMapper()
        result = mapper.map(
            final_direction=-0.3,
            final_magnitude=0.5,
            resonance_state="divergence",
            contradiction=None,
            enable_force_vector=False,
        )
        assert result.war_state == "FREEZE"
        assert 0.1 <= result.aggregate_position_cap_pct <= 0.2
        mask = result.allowed_style_mask
        assert mask["emergency"] is True
        for style in ("trend_follow", "breakout", "momentum", "mean_revert"):
            assert mask[style] is False


# ============================================================
# 额外测试 3: enable_force_vector 开关
# ============================================================
class TestForceVectorToggle:
    """enable_force_vector 开关与字节等价保证。"""

    def test_disable_force_vector_yields_none(self):
        """enable_force_vector=False → force_vectors=None。"""
        mapper = StrategicMapper()
        fvs = _make_force_vectors(confidence=0.9)
        result = mapper.map(
            final_direction=0.5,
            final_magnitude=0.6,
            resonance_state="resonance",
            force_vectors=fvs,
            enable_force_vector=False,
        )
        assert result.force_vectors is None

    def test_enable_force_vector_passes_through(self):
        """enable_force_vector=True → force_vectors 透传。"""
        mapper = StrategicMapper()
        fvs = _make_force_vectors(confidence=0.9)
        result = mapper.map(
            final_direction=0.5,
            final_magnitude=0.6,
            resonance_state="resonance",
            force_vectors=fvs,
            enable_force_vector=True,
        )
        assert result.force_vectors is not None
        assert "dao" in result.force_vectors


# ============================================================
# 额外测试 4: data_quality_warning
# ============================================================
class TestDataQualityWarning:
    """data_quality_warning → confidence 降级但 war_state 不变。"""

    def test_data_quality_warning_scales_confidence_keeps_state(self):
        mapper = StrategicMapper()
        fvs = _make_force_vectors(confidence=0.9)
        contradiction = _make_contradiction("data_quality_warning")

        # 基准（无矛盾）
        base = mapper.map(
            final_direction=0.5,
            final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=None,
            force_vectors=fvs,
            enable_force_vector=True,
        )
        # 带矛盾
        warned = mapper.map(
            final_direction=0.5,
            final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=contradiction,
            force_vectors=copy.deepcopy(fvs),
            enable_force_vector=True,
        )

        # war_state / cap 维持不变
        assert warned.war_state == base.war_state
        assert warned.aggregate_position_cap_pct == pytest.approx(
            base.aggregate_position_cap_pct
        )
        # force_vectors confidence 被 ×0.7
        assert warned.force_vectors["dao"].confidence == pytest.approx(0.9 * 0.7)
        # 原始输入未被修改（无副作用）
        assert fvs["dao"].confidence == pytest.approx(0.9)
