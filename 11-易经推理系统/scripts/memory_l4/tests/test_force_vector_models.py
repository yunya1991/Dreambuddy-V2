"""TC1: 力向量数据结构测试。

验证 ForceVector 及关联 dataclass 字段类型和范围约束。
对应 Spec §二 ForceVector / §三 FeatureCorrelation / PrimaryContradiction / PCAResonance /
§四 CycleComparison / §三-A ElasticityBeta / ContradictionTransform / StrategicLayerOutput。
"""
import pytest
import sys
from pathlib import Path

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.models import (
    ForceVector,
    FeatureCorrelation,
    PrimaryContradiction,
    PCAResonance,
    CycleComparison,
    ElasticityBeta,
    ContradictionTransform,
    StrategicLayerOutput,
)


class TestForceVector:
    """TC1: ForceVector 含 10 字段，类型范围正确。"""

    def test_force_vector_fields_and_ranges(self):
        fv = ForceVector(
            dimension="dao",
            direction=0.5,
            magnitude=0.8,
            confidence=0.7,
            velocity=0.1,
            acceleration=0.05,
            kalman_direction=0.48,
            kalman_magnitude=0.78,
            dominant=True,
            weight=0.3,
        )
        assert fv.dimension == "dao"
        assert -1.0 <= fv.direction <= 1.0
        assert 0.0 <= fv.magnitude
        assert 0.0 <= fv.confidence <= 1.0
        assert isinstance(fv.dominant, bool)
        assert 0.0 <= fv.weight <= 1.0

    def test_force_vector_negative_direction(self):
        fv = ForceVector(
            dimension="tian", direction=-0.8, magnitude=1.2,
            confidence=0.3, velocity=-0.2, acceleration=0.0,
            kalman_direction=-0.75, kalman_magnitude=1.1,
            dominant=False, weight=0.15,
        )
        assert -1.0 <= fv.direction <= 1.0
        assert fv.direction < 0

    def test_force_vector_all_dimensions(self):
        for dim in ("dao", "tian", "di", "jiang", "fa"):
            fv = ForceVector(
                dimension=dim, direction=0.0, magnitude=0.0,
                confidence=0.0, velocity=0.0, acceleration=0.0,
                kalman_direction=0.0, kalman_magnitude=0.0,
                dominant=False, weight=0.0,
            )
            assert fv.dimension == dim


class TestFeatureCorrelation:
    """TC1: FeatureCorrelation 字段。"""

    def test_feature_correlation_fields(self):
        fc = FeatureCorrelation(
            feature_name="fedfunds_rate",
            dimension="tian",
            ic_30d=0.15,
            mi_30d=0.3,
            combined_score=0.21,
            rank=1,
            ic_weight=0.35,
            beta_weight=1.2,
            final_weight=0.42,
        )
        assert fc.feature_name == "fedfunds_rate"
        assert fc.dimension == "tian"
        assert -1.0 <= fc.ic_30d <= 1.0
        assert 0.0 <= fc.mi_30d <= 1.0
        assert fc.rank == 1


class TestPrimaryContradiction:
    """TC1: PrimaryContradiction 字段。"""

    def test_primary_contradiction_fields(self):
        pc = PrimaryContradiction(
            feature_name="stablecoin_mcap",
            dimension="dao",
            combined_score=0.35,
            rank_stability=0.85,
            all_features=[],
            dominant_dimension="dao",
            alignment="resonance",
            sign_alignment=0.8,
        )
        assert pc.feature_name == "stablecoin_mcap"
        assert pc.dominant_dimension == "dao"
        assert pc.alignment in ("resonance", "conflict", "divergence")


class TestPCAResonance:
    """TC1: PCAResonance 字段。"""

    def test_pca_resonance_fields(self):
        pr = PCAResonance(
            explained_ratio=0.65,
            sign_alignment=1.0,
            alignment="full_resonance",
            strength_coefficient=1.3,
            dominant_dimension="dao",
        )
        assert 0.0 <= pr.explained_ratio <= 1.0
        assert 0.0 <= pr.sign_alignment <= 1.0
        assert 0.3 <= pr.strength_coefficient <= 1.3


class TestCycleComparison:
    """TC1: CycleComparison 字段。"""

    def test_cycle_comparison_fields(self):
        cc = CycleComparison(
            direction_7d=0.5,
            direction_30d=0.4,
            magnitude_7d=0.6,
            magnitude_30d=0.5,
            resonance_state="resonance",
            strength_multiplier=1.2,
            final_direction=0.45,
            final_magnitude=0.6,
        )
        assert -1.0 <= cc.direction_7d <= 1.0
        assert cc.resonance_state in (
            "resonance", "emerging", "divergence", "persistent", "turning", "observation"
        )


class TestElasticityBeta:
    """TC1: ElasticityBeta 字段。"""

    def test_elasticity_beta_fields(self):
        eb = ElasticityBeta(
            beta_7d=0.3,
            beta_30d=0.8,
            beta_ratio=0.375,
            decay_signal=True,
            amplification_signal=False,
            decay_days=4,
            amplification_days=0,
        )
        assert eb.beta_ratio == pytest.approx(0.375, rel=1e-3)
        assert isinstance(eb.decay_signal, bool)
        assert eb.decay_days >= 0


class TestContradictionTransform:
    """TC1: ContradictionTransform 字段。"""

    def test_contradiction_transform_fields(self):
        ct = ContradictionTransform(
            transforming=True,
            transform_type="elasticity_decay",
            trigger_conditions=["elasticity_decay", "dominant_shift"],
            confidence=0.33,
            monitoring_points=["β_7d/β_30d<0.5 持续3天"],
            data_quality_factor=1.0,
        )
        assert ct.transforming is True
        assert ct.transform_type in (
            "elasticity_decay", "elasticity_amplification", "dominant_shift",
            "resonance_break", "cbr_divergence", "data_quality_warning", "none",
        )
        assert 0.0 <= ct.confidence <= 1.0
        assert 0.0 <= ct.data_quality_factor <= 1.0


class TestStrategicLayerOutput:
    """TC1: StrategicLayerOutput 字段。"""

    def test_strategic_output_fields(self):
        so = StrategicLayerOutput(
            war_state="ALLOW",
            aggregate_position_cap_pct=0.8,
            allowed_style_mask={"trend_follow": True, "breakout": True},
            position_mult=1.0,
            five_scores={"dao": 75, "tian": 60},
            force_vectors={},
            pca_result=None,
            cycle_comparison=None,
            final_direction=0.5,
            final_magnitude=0.6,
            resonance_state="resonance",
            elasticity_beta=None,
            contradiction_transform=None,
            primary_contradiction="dao",
            monitoring_points=[],
        )
        assert so.war_state in ("ALLOW", "COOLDOWN", "FREEZE")
        assert 0.0 <= so.aggregate_position_cap_pct <= 1.0
        assert so.force_vectors is not None  # 可为空 dict
