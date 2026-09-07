"""T-G4: Shadow 字节等价测试。

验证 enable_force_vector=True vs False 时：
  - war_state / aggregate_position_cap_pct / allowed_style_mask / position_mult 完全一致
  - force_vectors 仅在开启时存在，关闭时为 None
  - five_scores 不受影响

对应实施计划 §1.2 T-G4 硬门槛。
"""
import pytest
import sys
from pathlib import Path

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.models import ContradictionTransform
from force_vector.strategic_mapper import StrategicMapper


class TestShadowByteEquivalence:
    """T-G4: enable_force_vector=True vs False，下游接口字节等价。"""

    @pytest.fixture
    def mapper(self):
        return StrategicMapper()

    @pytest.fixture
    def neutral_contradiction(self):
        return ContradictionTransform(
            transforming=False,
            transform_type="none",
            trigger_conditions=[],
            confidence=0.0,
            monitoring_points=[],
            data_quality_factor=1.0,
        )

    def test_resonance_bullish_equivalence(self, mapper, neutral_contradiction):
        """共振+方向>0：开/关输出一致。"""
        out_on = mapper.map(
            final_direction=0.5, final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=neutral_contradiction,
            enable_force_vector=True,
        )
        out_off = mapper.map(
            final_direction=0.5, final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=neutral_contradiction,
            enable_force_vector=False,
        )
        assert out_on.war_state == out_off.war_state
        assert out_on.aggregate_position_cap_pct == out_off.aggregate_position_cap_pct
        assert out_on.allowed_style_mask == out_off.allowed_style_mask
        assert out_on.position_mult == out_off.position_mult
        assert out_off.force_vectors is None

    def test_freeze_equivalence(self, mapper, neutral_contradiction):
        """FREEZE 场景：开/关输出一致。"""
        out_on = mapper.map(
            final_direction=-0.5, final_magnitude=0.4,
            resonance_state="divergence",
            contradiction=neutral_contradiction,
            enable_force_vector=True,
        )
        out_off = mapper.map(
            final_direction=-0.5, final_magnitude=0.4,
            resonance_state="divergence",
            contradiction=neutral_contradiction,
            enable_force_vector=False,
        )
        assert out_on.war_state == out_off.war_state == "FREEZE"
        assert out_on.aggregate_position_cap_pct == out_off.aggregate_position_cap_pct
        assert out_on.allowed_style_mask == out_off.allowed_style_mask
        assert out_off.force_vectors is None

    def test_contradiction_transform_equivalence(self, mapper):
        """矛盾转化触发时：开/关的 war_state/cap/mask 仍一致。"""
        ct = ContradictionTransform(
            transforming=True,
            transform_type="elasticity_decay",
            trigger_conditions=["elasticity_decay"],
            confidence=0.17,
            monitoring_points=["β_ratio<0.5"],
            data_quality_factor=1.0,
        )
        out_on = mapper.map(
            final_direction=0.5, final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=ct,
            enable_force_vector=True,
        )
        out_off = mapper.map(
            final_direction=0.5, final_magnitude=0.6,
            resonance_state="resonance",
            contradiction=ct,
            enable_force_vector=False,
        )
        # 矛盾转化影响 war_state/cap/mask，但开/关必须一致
        assert out_on.war_state == out_off.war_state
        assert out_on.aggregate_position_cap_pct == out_off.aggregate_position_cap_pct
        assert out_on.allowed_style_mask == out_off.allowed_style_mask
        assert out_off.force_vectors is None

    def test_five_scores_unchanged(self, mapper, neutral_contradiction):
        """five_scores 不受 enable_force_vector 影响。"""
        scores = {"dao": 75, "tian": 60, "di": 50, "jiang": 65, "fa": 70}
        out_on = mapper.map(
            final_direction=0.3, final_magnitude=0.4,
            resonance_state="persistent",
            contradiction=neutral_contradiction,
            five_scores=scores,
            enable_force_vector=True,
        )
        out_off = mapper.map(
            final_direction=0.3, final_magnitude=0.4,
            resonance_state="persistent",
            contradiction=neutral_contradiction,
            five_scores=scores,
            enable_force_vector=False,
        )
        assert out_on.five_scores == out_off.five_scores == scores
