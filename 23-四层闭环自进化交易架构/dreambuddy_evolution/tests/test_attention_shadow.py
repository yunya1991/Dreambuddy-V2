"""B-03: Attention A_dim shadow tests."""
from __future__ import annotations

import importlib

from dreambuddy_evolution.core.attention_shadow import (
    aggregate_attention,
    clear_last_attn_weights,
    compute_a_dim_shadow,
    get_last_attn_weights,
    record_last_attn_weights,
)
from dreambuddy_evolution.core.dimension_mapping import (
    DEFAULT_C_DIMENSIONS,
    c_dim_to_three,
)


def _weights(head_values):
    """构造 (B=1, H, 1, N=1) 的 nested list attention weights."""
    return [[[[float(value)] for _ in range(1)] for value in head_values]]


class TestAttentionShadow:
    def test_c_dim_to_three(self):
        assert c_dim_to_three("C1") == "fundamental"
        assert c_dim_to_three("C2") == "technical"
        assert c_dim_to_three("C4") == "macro"
        assert c_dim_to_three("C8") == "macro"
        assert c_dim_to_three("news") == "technical"
        assert c_dim_to_three("unknown") is None

    def test_aggregate_macro_dominant(self):
        # C4/C8 高权重 → macro
        result = aggregate_attention(
            _weights([0.01, 0.01, 0.01, 0.5, 0.01, 0.01, 0.4, 0.01])
        )
        assert result["available"] is True
        assert result["A_dim"] == "macro"
        assert result["A_strength"] > 0.5

    def test_aggregate_technical_dominant(self):
        # C2/C7/news 高权重 → technical
        result = aggregate_attention(
            _weights([0.01, 0.5, 0.01, 0.01, 0.01, 0.4, 0.01, 0.4])
        )
        assert result["available"] is True
        assert result["A_dim"] == "technical"

    def test_aggregate_invalid_fail_open(self):
        assert aggregate_attention(None)["available"] is False
        assert aggregate_attention([])["available"] is False
        assert aggregate_attention(_weights([0.1, 0.2]))["available"] is False

    def test_compute_shadow_agreement(self):
        clear_last_attn_weights()
        shadow = compute_a_dim_shadow(
            {"dimension": "C4"},
            attn_weights=_weights([0.01, 0.01, 0.01, 0.5, 0.01, 0.01, 0.4, 0.01]),
        )
        assert shadow["available"] is True
        assert shadow["a_dim_identifier"] == "macro"
        assert shadow["a_dim_attention"] == "macro"
        assert shadow["agreement"] is True
        assert shadow["shadow_only"] is True

    def test_compute_shadow_disagreement(self):
        shadow = compute_a_dim_shadow(
            {"dimension": "C4"},
            attn_weights=_weights([0.01, 0.5, 0.01, 0.01, 0.01, 0.4, 0.01, 0.4]),
        )
        assert shadow["a_dim_identifier"] == "macro"
        assert shadow["a_dim_attention"] == "technical"
        assert shadow["agreement"] is False

    def test_compute_shadow_unavailable(self):
        clear_last_attn_weights()
        shadow = compute_a_dim_shadow({"dimension": "C4"})
        assert shadow["available"] is False
        assert shadow["a_dim_identifier"] == "macro"
        assert shadow["a_dim_attention"] is None
        assert shadow["agreement"] is None

    def test_record_get_clear_cache(self):
        clear_last_attn_weights()
        weights = _weights([0.1] * 8)
        record_last_attn_weights(weights)
        assert get_last_attn_weights() == weights
        shadow = compute_a_dim_shadow({"dimension": "C1"})
        assert shadow["available"] is True
        clear_last_attn_weights()
        assert get_last_attn_weights() is None

    def test_switches_default_off(self):
        from dreambuddy_evolution.agi_config import get_switch

        assert get_switch("enable_attention_a_dim", False) is False
        assert get_switch("enable_a_dim_c_to_3", False) is False

    def test_cross_validation_gate_import_without_torch(self):
        module = importlib.import_module("dreambuddy_evolution.core.cross_validation_gate")
        assert module.CrossValidationGate is not None

    def test_attention_aggregator_import_without_torch(self):
        module = importlib.import_module("dreambuddy_evolution.core.attention_aggregator")
        assert module.AttentionAggregator is not None

    def test_cv_gate_matches_three_dim(self):
        from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

        gate = CrossValidationGate(dimensions=list(DEFAULT_C_DIMENSIONS))
        result = gate.compare("macro", 1.0, "macro", 1.0, {})
        assert result["confidence_mult"] == 1.15

    def test_legacy_c_dim_never_matches_three_dim(self):
        """记录当前 bug：A_dim 传 C4 时无法与 G_dim=macro 匹配."""
        from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

        gate = CrossValidationGate(dimensions=list(DEFAULT_C_DIMENSIONS))
        result = gate.compare("macro", 1.0, "C4", 1.0, {})
        assert result["confidence_mult"] == 0.9