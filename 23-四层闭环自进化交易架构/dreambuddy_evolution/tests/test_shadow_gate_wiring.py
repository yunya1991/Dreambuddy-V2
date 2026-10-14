"""Shadow 门禁接线测试. SPEC §7"""
from __future__ import annotations

import json


def test_pipeline_init_reconciles(tmp_path, monkeypatch):
    from dreambuddy_evolution.agi_config import get_switch, set_switch
    set_switch("enable_shadow_auto_activation", True)
    set_switch("enable_causal_historical_samples", False)

    # 把默认状态目录重定向到 tmp_path（reconcile 读盘来源）
    from dreambuddy_evolution.core import shadow_activation_gate as sag
    monkeypatch.setattr(sag, "DEFAULT_STATE_DIR", tmp_path, raising=False)

    (tmp_path / "enable_causal_historical_samples.json").write_text(
        json.dumps({"switch": "enable_causal_historical_samples",
                    "activated_at": "2026-10-14T18:00:00+08:00",
                    "min_days": 7, "min_n": 500, "observations": []}),
        encoding="utf-8",
    )
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
    EvolutionPipeline(gene_root=tmp_path)
    assert get_switch("enable_causal_historical_samples", False) is True


def test_identify_calls_maybe_activate(monkeypatch):
    from dreambuddy_evolution.core import shadow_activation_gate as sag
    called = {"n": 0}

    def _spy(self):
        called["n"] += 1
        return False

    monkeypatch.setattr(sag.ShadowActivationGate, "maybe_activate", _spy, raising=True)
    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )
    ident = PrimaryContradictionIdentifier()
    ident.identify(paths=[])  # <2 路径 → neutral，门禁仍须被调用
    assert called["n"] >= 1
