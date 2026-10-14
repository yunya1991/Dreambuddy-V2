"""
Phase 3.1: PrimaryContradictionIdentifier TDD 测试
SPEC-主要矛盾识别与最小阻力路径设计.md §4.2

核心哲学: 主要矛盾识别 — 矛盾论 §主要矛盾 + §矛盾主要方面
HC-AGI-18: 异常必须 FAIL-OPEN，返回 neutral 兜底
HC-AGI-23: 至少 2 路径才做矛盾分析，单路径返回 neutral
"""
from __future__ import annotations

import pytest


class TestPrimaryContradictionIdentifier:
    """主要矛盾识别器单元测试"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        assert PrimaryContradictionIdentifier is not None

    def test_identify_resonance_all_long(self):
        """共振全多: 多路径方向一致 → 主要矛盾方向 long"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3},
            {"path_id": "p3", "source": "strategic", "direction": "long",
             "expected_return": 0.2, "confidence": 0.6, "resistance": 0.4},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["direction"] == "long"
        # Fix 4: 全做多 = 完全共识 → 矛盾强度为 0（矛盾 = 对立，非一致）
        # 但方向仍为 long（优势方）
        assert result["strength"] == 0.0
        assert 0.0 <= result["strength"] <= 1.0

    def test_identify_resonance_all_short(self):
        """共振全空: 多路径方向一致 → 主要矛盾方向 short"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "short",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
            {"path_id": "p2", "source": "bdsm", "direction": "short",
             "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["direction"] == "short"
        # Fix 4: 全做空 = 完全共识 → 矛盾强度为 0
        assert result["strength"] == 0.0

    def test_arbitrate_conflict_long_vs_short(self):
        """冲突裁决: long vs short 方向冲突 → 4维评分法识别主导者"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.9, "resistance": 0.1},
            {"path_id": "p2", "source": "strategic", "direction": "short",
             "expected_return": 0.05, "confidence": 0.3, "resistance": 0.7},
        ]
        result = identifier.identify(paths, {}, {})
        # long 方力量更大 (0.9 > 0.3)
        assert result["direction"] == "long"
        assert result["confidence"] >= 0.0

    def test_neutral_default_when_single_path(self):
        """HC-AGI-23: 单路径返回 neutral 兜底"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["direction"] == "neutral"
        assert result["strength"] == 0.0

    def test_neutral_default_when_empty_paths(self):
        """空路径列表 → neutral 兜底"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        result = identifier.identify([], {}, {})
        assert result["direction"] == "neutral"
        assert result["strength"] == 0.0

    def test_fail_open_on_exception(self):
        """HC-AGI-18: 异常 FAIL-OPEN，返回 neutral 兜底"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        # 传入畸形数据触发异常
        bad_paths = "not_a_list"  # type: ignore
        result = identifier.identify(bad_paths, {}, {})
        assert result["direction"] == "neutral"
        assert result["strength"] == 0.0

    def test_dominance_threshold(self):
        """主导阈值: 力量对比差距大 → 高置信度"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.95, "resistance": 0.05},
            {"path_id": "p2", "source": "strategic", "direction": "short",
             "expected_return": 0.01, "confidence": 0.1, "resistance": 0.9},
        ]
        result = identifier.identify(paths, {}, {})
        # long 力量远大于 short
        assert result["direction"] == "long"
        assert result["confidence"] > 0.5

    def test_dimension_mapping(self):
        """C1-C8 维度映射: BDSM → C1, BCRM → C3 等"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bdsm", "direction": "long",
             "expected_return": 0.15, "confidence": 0.9, "resistance": 0.1},
            {"path_id": "p2", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.7, "resistance": 0.3},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["dimension"] in ("C1", "C2", "C3", "C4", "C6", "C7", "C8")

    def test_output_has_required_fields(self):
        """输出包含所有必需字段"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3},
        ]
        result = identifier.identify(paths, {}, {})
        required = {"dimension", "direction", "strength", "confidence",
                    "cause_score", "effort_result", "continuation_score"}
        assert required.issubset(result.keys())


class _FakeCausalEngine:
    """测试桩：返回预设 ATE 结果，避免依赖真实因果推断."""

    def __init__(self, ate_result):
        self._result = ate_result

    def estimate_ate(self, X, treatment, y, method="dml"):
        return dict(self._result)


class TestCausalATEEnhancement:
    """W4 CausalEngine ATE 增强的降级契约 (HC-AGI-08).

    契约：因果 DAG/ATE 需 ≥500 样本；样本不足时应为中性 no-op，
    不得调整 strength。只有真正估计出 ATE（method ∈ dml/s/t/linear）
    才允许按显著性调整。
    """

    def _make_identifier(self):
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        return PrimaryContradictionIdentifier()

    def _paths(self, direction="long"):
        return [
            {"path_id": "p1", "source": "bcrm", "direction": direction,
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
            {"path_id": "p2", "source": "bdsm", "direction": direction,
             "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3},
        ]

    def test_insufficient_samples_is_noop(self):
        """HC-AGI-08: 样本不足(method=insufficient_samples) → strength 不变"""
        identifier = self._make_identifier()
        engine = _FakeCausalEngine({
            "ate": 0.0, "lower_bound": 0.0, "upper_bound": 0.0,
            "method": "insufficient_samples", "significant": False,
        })
        primary = {"direction": "long", "strength": 0.8}
        out = identifier._enhance_with_causal_ate(
            primary, self._paths(), {}, engine)
        assert out["strength"] == 0.8

    def test_small_sample_integration_is_noop(self):
        """集成场景: 路径数(≈6)远小于500 → 真实引擎返回中性 → strength 不变

        A2: 显式关闭 enable_causal_historical_samples，确认退回 paths 分支
        （样本恒 <500），避免开关泄漏导致行为变化。
        """
        from dreambuddy_evolution.core.causal_engine import CausalEngine
        from dreambuddy_evolution.agi_config import AGI_SWITCHES
        identifier = self._make_identifier()
        paths = [
            {"path_id": f"p{i}", "source": "bcrm", "direction": "long",
             "expected_return": 0.1 * i, "confidence": 0.5 + 0.05 * i,
             "resistance": 0.2}
            for i in range(1, 7)
        ]
        prev = AGI_SWITCHES.get("enable_causal_historical_samples", False)
        AGI_SWITCHES["enable_causal_historical_samples"] = False
        try:
            primary = {"direction": "long", "strength": 0.8}
            out = identifier._enhance_with_causal_ate(
                primary, paths, {}, CausalEngine())
            assert out["strength"] == 0.8
            assert out["causal_ate"]["method"] == "insufficient_samples"
        finally:
            AGI_SWITCHES["enable_causal_historical_samples"] = prev

    def test_insignificant_observational_source_is_noop(self):
        """#14（v5, SPEC §6.2 态B）: 观测性源 |ate|<τ 且 CI⊆(−τ,τ) → strength 逐位不变.

        替代旧 A1 恒定 ×0.95 契约（用户 2026-10-14 裁决采用三态门禁）。
        """
        identifier = self._make_identifier()
        engine = _FakeCausalEngine({
            "ate": 0.0016, "lower_bound": -0.00045, "upper_bound": 0.00371,
            "method": "causalml_dml", "significant": False,
            "ci_method": "block_bootstrap",
        })
        primary = {"direction": "long", "strength": 0.8}
        out = identifier._enhance_with_causal_ate(
            primary, self._paths(), {}, engine)
        assert out["strength"] == 0.8

    def test_real_estimate_significant_aligned_boosts(self):
        """态A（CI 不含 0 且 |ate|≥τ）且同向 → 增强 ×1.15"""
        identifier = self._make_identifier()
        engine = _FakeCausalEngine({
            "ate": 0.3, "lower_bound": 0.1, "upper_bound": 0.5,
            "method": "causalml_dml", "significant": True,
            "ci_method": "block_bootstrap",
        })
        primary = {"direction": "long", "strength": 0.8}
        out = identifier._enhance_with_causal_ate(
            primary, self._paths(), {}, engine)
        assert out["strength"] == pytest.approx(0.8 * 1.15)

    def test_engine_error_is_noop(self):
        """引擎异常 method=error → 中性 no-op，不调整 strength"""
        identifier = self._make_identifier()
        engine = _FakeCausalEngine({
            "ate": 0.0, "lower_bound": 0.0, "upper_bound": 0.0,
            "method": "error", "significant": False,
        })
        primary = {"direction": "long", "strength": 0.8}
        out = identifier._enhance_with_causal_ate(
            primary, self._paths(), {}, engine)
        assert out["strength"] == 0.8

    # ------------------------------------------------------------------
    # A2: 历史样本接入（开关 enable_causal_historical_samples）
    # ------------------------------------------------------------------

    def test_real_ate_from_historical_samples_adjusts_strength(self, tmp_path):
        """#10: 开关开 + 充足历史样本 → 真 CausalEngine 估计出 ATE（非降级）."""
        import json
        import numpy as np
        from dreambuddy_evolution.core.causal_engine import CausalEngine
        from dreambuddy_evolution.core.causal_sample_store import CausalSampleStore
        from dreambuddy_evolution.agi_config import AGI_SWITCHES

        boot = tmp_path / "boot.jsonl"
        rng = np.random.default_rng(2026)
        with open(boot, "w", encoding="utf-8") as f:
            for _ in range(800):
                rup = float(rng.normal(0.0, 1.0))
                rec = {
                    "state": {
                        "R_up": rup,
                        "R_down": float(rng.normal(0.0, 1.0)),
                        "R_smooth": float(rng.normal(0.0, 1.0)),
                        "R_flow": float(rng.normal(0.0, 1.0)),
                        "R_reflexivity": float(rng.normal(0.0, 1.0)),
                        "quality_score": 1.0,
                    },
                    "action": "long",
                    "reward": float(1.0 * rup + rng.normal(0.0, 0.3)),
                }
                f.write(json.dumps(rec) + "\n")

        identifier = self._make_identifier()
        identifier._causal_sample_store = CausalSampleStore(
            shadow_path=str(boot), live_path=str(tmp_path / "live.json")
        )
        prev = AGI_SWITCHES.get("enable_causal_historical_samples", False)
        AGI_SWITCHES["enable_causal_historical_samples"] = True
        try:
            primary = {"direction": "long", "strength": 0.8}
            out = identifier._enhance_with_causal_ate(
                primary, self._paths(), {}, CausalEngine())
            assert out["causal_ate"]["method"] in (
                "causalml_dml", "causalml_s", "causalml_t", "linear_regression"
            )
        finally:
            AGI_SWITCHES["enable_causal_historical_samples"] = prev

    def test_insufficient_still_noop(self, tmp_path):
        """#11: 开关开但历史样本 <500 → strength 不变（A1 契约不回归）."""
        from dreambuddy_evolution.core.causal_engine import CausalEngine
        from dreambuddy_evolution.core.causal_sample_store import CausalSampleStore
        from dreambuddy_evolution.agi_config import AGI_SWITCHES

        identifier = self._make_identifier()
        identifier._causal_sample_store = CausalSampleStore(
            shadow_path=str(tmp_path / "nope.jsonl"),
            live_path=str(tmp_path / "none.json"),
        )
        prev = AGI_SWITCHES.get("enable_causal_historical_samples", False)
        AGI_SWITCHES["enable_causal_historical_samples"] = True
        try:
            primary = {"direction": "long", "strength": 0.8}
            out = identifier._enhance_with_causal_ate(
                primary, self._paths(), {}, CausalEngine())
            assert out["strength"] == 0.8
            assert out["causal_ate"]["method"] == "insufficient_samples"
        finally:
            AGI_SWITCHES["enable_causal_historical_samples"] = prev

    def test_switch_off_reverts_to_live_paths(self):
        """#12: 开关关 → 退回 paths 分支（不读历史样本），旧契约不变."""
        from dreambuddy_evolution.agi_config import AGI_SWITCHES

        identifier = self._make_identifier()
        engine = _FakeCausalEngine({
            "ate": 0.3, "lower_bound": 0.1, "upper_bound": 0.5,
            "method": "causalml_dml", "significant": True,
            "ci_method": "block_bootstrap",
        })
        prev = AGI_SWITCHES.get("enable_causal_historical_samples", False)
        AGI_SWITCHES["enable_causal_historical_samples"] = False
        try:
            primary = {"direction": "long", "strength": 0.8}
            out = identifier._enhance_with_causal_ate(
                primary, self._paths(), {}, engine)
            assert out["strength"] == pytest.approx(0.8 * 1.15)
        finally:
            AGI_SWITCHES["enable_causal_historical_samples"] = prev


# ------------------------------------------------------------------
# A2 v5: 经济显著性三态门禁 + 效应量/口径报告（SPEC §5 #15-#20）
# ------------------------------------------------------------------

_REAL_ATE_CACHE: dict = {}


def _real_observational_ate():
    """真实 CausalEngine 在 ≥500 历史样本上的 ATE 结果（缓存，避免重复昂贵 DML）."""
    if "r" in _REAL_ATE_CACHE:
        return _REAL_ATE_CACHE["r"]
    import json
    import os
    import tempfile

    import numpy as np

    from dreambuddy_evolution.agi_config import AGI_SWITCHES
    from dreambuddy_evolution.core.causal_engine import CausalEngine
    from dreambuddy_evolution.core.causal_sample_store import CausalSampleStore
    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )

    d = tempfile.mkdtemp()
    boot = os.path.join(d, "boot.jsonl")
    rng = np.random.default_rng(2026)
    with open(boot, "w", encoding="utf-8") as f:
        for _ in range(800):
            rup = float(rng.normal(0.0, 1.0))
            rec = {
                "state": {
                    "R_up": rup,
                    "R_down": float(rng.normal(0.0, 1.0)),
                    "R_smooth": float(rng.normal(0.0, 1.0)),
                    "R_flow": float(rng.normal(0.0, 1.0)),
                    "R_reflexivity": float(rng.normal(0.0, 1.0)),
                    "quality_score": 1.0,
                },
                "action": "long",
                "reward": float(0.0005 * rup + rng.normal(0.0, 0.3)),
            }
            f.write(json.dumps(rec) + "\n")

    ident = PrimaryContradictionIdentifier()
    ident._causal_sample_store = CausalSampleStore(
        shadow_path=boot, live_path=os.path.join(d, "live.json")
    )
    prev = AGI_SWITCHES.get("enable_causal_historical_samples", False)
    AGI_SWITCHES["enable_causal_historical_samples"] = True
    try:
        out = ident._enhance_with_causal_ate(
            {"direction": "long", "strength": 0.8},
            [{"path_id": "p1", "source": "bcrm", "direction": "long",
              "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
             {"path_id": "p2", "source": "bdsm", "direction": "long",
              "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3}],
            {}, CausalEngine())
    finally:
        AGI_SWITCHES["enable_causal_historical_samples"] = prev
    _REAL_ATE_CACHE["r"] = out["causal_ate"]
    return _REAL_ATE_CACHE["r"]


class TestAteGateContractV5:
    """A2 v5: 三态门禁 + 效应量/ci_method/positivity/试错披露（SPEC §6.2/§2.5）."""

    def test_ate_report_contains_effect_size_and_ci_method(self):
        """#15: 观测性源 ATE 结果必含 effect_size（Cohen's d）与 ci_method."""
        r = _real_observational_ate()
        assert "effect_size" in r and isinstance(r["effect_size"], float)
        assert r["ci_method"] == "block_bootstrap"

    def test_tost_equivalence_gate_classification(self):
        """#16: |ate|<τ 且 CI⊆(−τ,τ) → 态B；CI 不含 0 且 |ate|≥τ → 态A."""
        from dreambuddy_evolution.core.contradiction_identifier import (
            classify_ate_state,
        )
        b = {"ate": 0.0016, "lower_bound": -0.00045, "upper_bound": 0.00371,
             "method": "causalml_dml", "ci_method": "block_bootstrap"}
        a = {"ate": 0.30, "lower_bound": 0.10, "upper_bound": 0.50,
             "method": "causalml_dml", "ci_method": "block_bootstrap"}
        assert classify_ate_state(b, 0.05) == "B"
        assert classify_ate_state(a, 0.05) == "A"

    def test_positivity_diagnostic_reported(self):
        """#17: ATE 结果含 positivity 诊断字段（仅诊断不阻断）."""
        r = _real_observational_ate()
        p = r.get("positivity")
        assert isinstance(p, dict)
        assert {"tail_ratio", "ate_trimmed", "trimmed_n"}.issubset(p.keys())

    def test_ate_returns_block_bootstrap_ci_method(self):
        """#18: 观测性源 CI 口径为 block_bootstrap；门禁拒收 iid/asymptotic（→态C）."""
        from dreambuddy_evolution.core.contradiction_identifier import (
            classify_ate_state,
        )
        r = _real_observational_ate()
        assert r["ci_method"] == "block_bootstrap"
        rej = dict(r)
        rej["ci_method"] = "iid_bootstrap"
        assert classify_ate_state(rej, 0.05) == "C"

    def test_sesoi_threshold_robustness(self):
        """#19: τ∈{0.02,0.05,0.1} 三档判定态一致（观测性源均落态B）."""
        from dreambuddy_evolution.core.contradiction_identifier import (
            SESOI_TAU_ROBUSTNESS,
            classify_ate_state,
        )
        obs = {"ate": 0.00163, "lower_bound": -0.00045, "upper_bound": 0.00371,
               "method": "causalml_dml", "ci_method": "block_bootstrap"}
        states = {classify_ate_state(obs, t) for t in SESOI_TAU_ROBUSTNESS}
        assert states == {"B"}

    def test_trial_count_disclosed_in_report(self):
        """#20: 结果含预注册试错次数 trial_count 与 FDR 折减字段."""
        r = _real_observational_ate()
        assert r["trial_count"] == 1
        assert "fdr_adjusted" in r
