"""
Shadow ATE 评估器 TDD 测试
SPEC-Shadow验证自动放量门禁.md §10 #13-#14
"""
from __future__ import annotations

import numpy as np


class _FakeStore:
    def build_ate_samples(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(800, 2))
        treatment = (X[:, 0] > 0).astype(np.int32)
        y = 0.08 * treatment + rng.normal(scale=0.1, size=800)
        return {"X": X, "treatment": treatment, "y": y, "source": "bootstrap"}


class _EmptyStore:
    def build_ate_samples(self):
        return None


class _FakeEngine:
    def __init__(self, *a, **k):
        pass

    def estimate_ate(self, X, treatment, y, method="dml"):
        return {"ate": 0.08, "lower_bound": 0.03, "upper_bound": 0.13,
                "method": "causalml_dml", "ci_method": "block_bootstrap",
                "significant": True}


def _gate(tmp_path):
    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    return ShadowActivationGate("enable_causal_historical_samples", state_dir=tmp_path)


def test_13_evaluator_records_state_a(tmp_path, monkeypatch):
    from dreambuddy_evolution.core import causal_sample_store as css
    from dreambuddy_evolution.core import causal_engine as ce
    from dreambuddy_evolution.core import shadow_ate_evaluator as ev

    monkeypatch.setattr(css, "CausalSampleStore", lambda *a, **k: _FakeStore())
    monkeypatch.setattr(ce, "CausalEngine", _FakeEngine)

    obs = ev.evaluate_and_record(_gate(tmp_path))
    assert obs is not None
    assert obs["gate_state"] == "A"
    assert obs["n"] == 800


def test_14_evaluator_no_obs_when_no_samples(tmp_path, monkeypatch):
    from dreambuddy_evolution.core import causal_sample_store as css
    from dreambuddy_evolution.core import shadow_ate_evaluator as ev

    monkeypatch.setattr(css, "CausalSampleStore", lambda *a, **k: _EmptyStore())
    assert ev.evaluate_and_record(_gate(tmp_path)) is None


def test_script_module_importable():
    import dreambuddy_evolution.scripts.shadow_ate_eval as s
    assert callable(s.main)
