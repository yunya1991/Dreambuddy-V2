"""N-P1a 多源加权聚合测试（RED 阶段）。

验收标准：
- 默认等权：p = pass / active
- 自定义权重：p = Σ(wᵢ·vᵢ) / Σ(wᵢ)
- 全 abstain → p=None（回退布尔）
- 权重归一化不影响结果（加权比例不变）
- StageWeights 可从 dict 构造，缺失 stage 用默认 1.0
- 单信号权重为 0 时被排除
"""
import pytest


def test_module_importable():
    from weighted_aggregation import (
        StageWeights, compute_weighted_p,
    )


# ---------------------------------------------------------------------------
# StageWeights
# ---------------------------------------------------------------------------

def test_default_weights_equal():
    from weighted_aggregation import StageWeights
    sw = StageWeights()
    assert sw.get("cycle_consistency") == 1.0
    assert sw.get("factuality") == 1.0
    assert sw.get("unknown_stage") == 1.0  # 缺失默认 1.0


def test_custom_weights():
    from weighted_aggregation import StageWeights
    sw = StageWeights({"cycle_consistency": 2.0, "factuality": 3.0})
    assert sw.get("cycle_consistency") == 2.0
    assert sw.get("factuality") == 3.0
    assert sw.get("applicability") == 1.0  # 未配置默认 1.0


def test_weights_from_dict():
    from weighted_aggregation import StageWeights
    sw = StageWeights.from_dict({"cycle_consistency": 5.0})
    assert sw.get("cycle_consistency") == 5.0


def test_weight_must_be_nonnegative():
    from weighted_aggregation import StageWeights
    with pytest.raises(ValueError):
        StageWeights({"a": -1.0})


def test_zero_weight_excludes_stage():
    from weighted_aggregation import StageWeights
    sw = StageWeights({"a": 0.0, "b": 2.0})
    assert sw.get("a") == 0.0  # 保留但聚合时排除


# ---------------------------------------------------------------------------
# compute_weighted_p
# ---------------------------------------------------------------------------

def test_weighted_p_equal_weights():
    from weighted_aggregation import StageWeights, compute_weighted_p
    from verification_record import VerificationSignal
    sw = StageWeights()
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="fail", verifier_id="v2"),
    ]
    p, n_active, total_weight = compute_weighted_p(signals, sw)
    assert abs(p - 0.5) < 1e-9  # 等权: 1/(1+1)
    assert n_active == 2


def test_weighted_p_custom_weights():
    from weighted_aggregation import StageWeights, compute_weighted_p
    from verification_record import VerificationSignal
    sw = StageWeights({"a": 3.0, "b": 1.0})
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="fail", verifier_id="v2"),
    ]
    p, n_active, total_weight = compute_weighted_p(signals, sw)
    assert abs(p - 0.75) < 1e-9  # 3/(3+1)
    assert n_active == 2
    assert abs(total_weight - 4.0) < 1e-9


def test_weighted_p_abstain_excluded():
    from weighted_aggregation import StageWeights, compute_weighted_p
    from verification_record import VerificationSignal
    sw = StageWeights({"a": 2.0, "b": 1.0})
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="abstain", verifier_id="v2"),
        VerificationSignal(stage="c", verdict="fail", verifier_id="v3"),
    ]
    # a=2.0 pass, c=1.0 fail → p=2/(2+1)=0.667
    p, n_active, total_weight = compute_weighted_p(signals, sw)
    assert abs(p - 2.0 / 3.0) < 1e-9
    assert n_active == 2


def test_weighted_p_all_abstain_returns_none():
    from weighted_aggregation import StageWeights, compute_weighted_p
    from verification_record import VerificationSignal
    sw = StageWeights()
    signals = [
        VerificationSignal(stage="a", verdict="abstain", verifier_id="v1"),
    ]
    p, n_active, total_weight = compute_weighted_p(signals, sw)
    assert p is None
    assert n_active == 0
    assert total_weight == 0.0


def test_weighted_p_empty_returns_none():
    from weighted_aggregation import StageWeights, compute_weighted_p
    sw = StageWeights()
    p, n_active, total_weight = compute_weighted_p([], sw)
    assert p is None
    assert n_active == 0


def test_weighted_p_zero_weight_stages_excluded():
    from weighted_aggregation import StageWeights, compute_weighted_p
    from verification_record import VerificationSignal
    sw = StageWeights({"a": 0.0, "b": 1.0})
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="fail", verifier_id="v2"),
    ]
    # a 权重 0 被排除，只剩 b fail → p=0
    p, n_active, total_weight = compute_weighted_p(signals, sw)
    assert abs(p - 0.0) < 1e-9
    assert n_active == 1
    assert abs(total_weight - 1.0) < 1e-9


def test_weighted_p_normalization_invariance():
    """权重整体缩放不影响 p。"""
    from weighted_aggregation import StageWeights, compute_weighted_p
    from verification_record import VerificationSignal
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="fail", verifier_id="v2"),
    ]
    sw1 = StageWeights({"a": 1.0, "b": 1.0})
    sw2 = StageWeights({"a": 10.0, "b": 10.0})
    p1, _, _ = compute_weighted_p(signals, sw1)
    p2, _, _ = compute_weighted_p(signals, sw2)
    assert abs(p1 - p2) < 1e-9
