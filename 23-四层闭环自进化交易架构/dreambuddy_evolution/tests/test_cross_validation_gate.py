"""TDD-CV-002: CrossValidationGate — §5.1 五步交叉验证算法.

RED 阶段断言：
- 一致: confidence_mult == 1.15, shift_signal == False
- 分歧: confidence_mult == 0.9, shift_signal == True, divergence_count += 1
- 质变: divergence_count >= persistence + break_score >= threshold
       → quality_change=True, granger_reestimate_trigger=True
- Q5 加权: market_form_shift=True → score=1.0 ≥ 0.4 触发
- FAIL-OPEN: G_dim/A_dim None → 中性结果
- head_adjustment: 分歧时 A_dim 对应 head boost, G_dim 对应 head decay
"""
import pytest


def test_module_importable():
    """CrossValidationGate 模块可导入。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate
    assert CrossValidationGate is not None


def test_consistent_boost():
    """一致状态: confidence_mult == 1.15, shift_signal == False。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(persistence_threshold=5)
    result = gate.compare(
        G_dim="fundamental", G_conf=0.9,
        A_dim="fundamental", A_strength=0.8,
        structural_break={},
    )
    assert result["confidence_mult"] == 1.15
    assert result["shift_signal"] is False
    assert result["quality_change"] is False


def test_divergence_penalty():
    """分歧状态: confidence_mult == 0.9, shift_signal == True。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(persistence_threshold=5)
    result = gate.compare(
        G_dim="fundamental", G_conf=0.9,
        A_dim="macro", A_strength=0.7,
        structural_break={},
    )
    assert result["confidence_mult"] == 0.9
    assert result["shift_signal"] is True
    assert result["divergence_count"] == 1


def test_quality_change_on_persistent_divergence():
    """持续分歧 + 结构性断裂 → 质变。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(persistence_threshold=3)
    sb = {"market_form_shift": True}  # score = 1.0 ≥ 0.4
    for _ in range(3):
        r = gate.compare(
            G_dim="fundamental", G_conf=0.9,
            A_dim="macro", A_strength=0.7,
            structural_break=sb,
        )
    assert r["quality_change"] is True
    assert r["granger_reestimate_trigger"] is True
    assert r["new_main_dim"] == "macro"
    assert r["divergence_count"] == 0  # 质变后重置


def test_fail_open_on_none():
    """G_dim 或 A_dim 为 None → FAIL-OPEN 中性结果。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate()
    r = gate.compare(G_dim=None, G_conf=None, A_dim="macro", A_strength=0.7, structural_break={})
    assert r["confidence_mult"] == 1.0
    assert r["shift_signal"] is False
    assert r["quality_change"] is False


def test_head_adjustment_on_divergence():
    """分歧时 head_adjustment 包含 A_dim head 的 boost 和 G_dim head 的 decay。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(persistence_threshold=5)
    r = gate.compare(
        G_dim="fundamental", G_conf=0.9,
        A_dim="macro", A_strength=0.7,
        structural_break={},
    )
    assert r["head_adjustment"]  # 非空
    # macro head 应 boost (>1), fundamental head 应 decay (<1)
    macro_heads = gate.dim_to_heads("macro")
    fund_heads = gate.dim_to_heads("fundamental")
    for h in macro_heads:
        assert r["head_adjustment"][h] > 1.0
    for h in fund_heads:
        assert r["head_adjustment"][h] < 1.0


def test_structural_break_score():
    """Q5 加权共识得分计算。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate()
    assert gate._structural_break_score({"market_form_shift": True}) == 1.0
    assert gate._structural_break_score({"correlation_break": True}) == 0.6
    assert gate._structural_break_score({"volatility_regime_shift": True}) == 0.4
    assert gate._structural_break_score({
        "market_form_shift": True, "correlation_break": True, "volatility_regime_shift": True
    }) == 2.0
    assert gate._structural_break_score({}) == 0.0


def test_sprt_switches_to_neutral_on_low_consistency():
    """单链路持续与 baseline 不一致 → SPRT accept_h1 → 切换 both_none。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate()
    # 建立 baseline：双链路一致为 fundamental
    gate.compare(G_dim="fundamental", G_conf=0.9, A_dim="fundamental",
                 A_strength=0.8, structural_break={})
    assert gate._baseline_dim == "fundamental"

    # 降级模式中持续输出 macro（与 baseline 不一致）
    switched = False
    for _ in range(200):
        r = gate.compare(G_dim=None, G_conf=None, A_dim="macro",
                         A_strength=0.7, structural_break={})
        if r.get("degraded_mode") == "both_none":
            switched = True
            break
    assert switched, "SPRT 应在持续不一致后切换到 both_none"
