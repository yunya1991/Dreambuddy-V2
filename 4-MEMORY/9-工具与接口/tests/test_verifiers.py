"""验证器模块测试（RED 阶段）。

三个验证器：
- CycleConsistencyVerifier: 自洽性/矛盾检测
- FactualityVerifier: 事实性检查
- ApplicabilityVerifier: 上下文适用性
"""
import pytest


def test_module_importable():
    from verifiers import (
        BaseVerifier, CycleConsistencyVerifier,
        FactualityVerifier, ApplicabilityVerifier,
    )


# ---------------------------------------------------------------------------
# BaseVerifier 接口契约
# ---------------------------------------------------------------------------

def test_base_verifier_returns_signal_on_exception():
    """验证器异常时返回 abstain（FAIL-OPEN）。"""
    from verifiers import BaseVerifier
    from verification_record import VerificationSignal

    class BrokenVerifier(BaseVerifier):
        stage = "broken"
        def _verify(self, content, context=None, **kwargs):
            raise RuntimeError("boom")

    v = BrokenVerifier()
    sig = v.verify("any content")
    assert isinstance(sig, VerificationSignal)
    assert sig.verdict == "abstain"
    assert sig.stage == "broken"


def test_base_verifier_abstain_when_no_content():
    from verifiers import BaseVerifier

    class Dummy(BaseVerifier):
        stage = "dummy"
        def _verify(self, content, context=None, **kwargs):
            return "pass"

    v = Dummy()
    sig = v.verify("")
    assert sig.verdict == "abstain"  # 空内容无法验证


# ---------------------------------------------------------------------------
# CycleConsistencyVerifier
# ---------------------------------------------------------------------------

def test_cycle_consistency_pass_when_consistent():
    from verifiers import CycleConsistencyVerifier
    v = CycleConsistencyVerifier()
    sig = v.verify("使用 subprocess 时应设置 shell=True，这样可以正确传递环境变量。")
    assert sig.verdict == "pass"
    assert sig.stage == "cycle_consistency"


def test_cycle_consistency_fail_on_contradiction():
    from verifiers import CycleConsistencyVerifier
    v = CycleConsistencyVerifier()
    # 包含明显矛盾：应该用 X vs 不要用 X
    sig = v.verify("应该使用 shell=True。不要使用 shell=True，因为有安全风险。")
    assert sig.verdict == "fail"


def test_cycle_consistency_detects_opposite_pairs():
    from verifiers import CycleConsistencyVerifier
    v = CycleConsistencyVerifier()
    # 上升 vs 下降
    sig = v.verify("趋势会上升。趋势会下降。")
    assert sig.verdict == "fail"


def test_cycle_consistency_fail_on_very_short_content():
    from verifiers import CycleConsistencyVerifier
    v = CycleConsistencyVerifier()
    sig = v.verify("ok")
    assert sig.verdict == "fail"  # 极短内容不可能是有意义的经验


# ---------------------------------------------------------------------------
# FactualityVerifier
# ---------------------------------------------------------------------------

def test_factuality_pass_on_supported_facts():
    from verifiers import FactualityVerifier
    v = FactualityVerifier()
    # 有明确事实声明且无明显错误模式
    sig = v.verify("Python 3.9 不支持 dataclass 的 slots=True 参数。")
    assert sig.verdict in ("pass", "abstain")  # 无法外部验证时至少 abstain


def test_factuality_fail_on_obvious_error():
    from verifiers import FactualityVerifier
    v = FactualityVerifier()
    # 明显错误：Python 版本号不可能是 99.0
    sig = v.verify("Python 99.0 已经发布。")
    assert sig.verdict == "fail"


def test_factuality_abstain_when_no_factual_claims():
    from verifiers import FactualityVerifier
    v = FactualityVerifier()
    sig = v.verify("这是一个经验记录，没有具体的事实声明。")
    assert sig.verdict == "abstain"


def test_factuality_detects_invalid_version():
    from verifiers import FactualityVerifier
    v = FactualityVerifier()
    # 不合理的版本号
    sig = v.verify("使用 Python 3.99.0 的新特性。")
    assert sig.verdict == "fail"


# ---------------------------------------------------------------------------
# ApplicabilityVerifier
# ---------------------------------------------------------------------------

def test_applicability_pass_when_relevant():
    from verifiers import ApplicabilityVerifier
    v = ApplicabilityVerifier()
    sig = v.verify(
        "subprocess 设置环境变量时应使用 env 参数",
        context="如何在 Python subprocess 中设置环境变量",
    )
    assert sig.verdict == "pass"


def test_applicability_fail_when_irrelevant():
    from verifiers import ApplicabilityVerifier
    v = ApplicabilityVerifier()
    sig = v.verify(
        "数据库索引优化建议",
        context="如何在 Python subprocess 中设置环境变量",
    )
    assert sig.verdict == "fail"


def test_applicability_abstain_without_context():
    from verifiers import ApplicabilityVerifier
    v = ApplicabilityVerifier()
    sig = v.verify("任何内容")
    assert sig.verdict == "abstain"  # 无 context 无法判断适用性


def test_applicability_partial_overlap():
    from verifiers import ApplicabilityVerifier
    v = ApplicabilityVerifier()
    # 部分关键词重叠
    sig = v.verify(
        "Python 的 subprocess 模块可以执行命令",
        context="subprocess 环境变量",
    )
    assert sig.verdict in ("pass", "fail")  # 部分重叠，不是 abstain


# ---------------------------------------------------------------------------
# Verifier 注册表
# ---------------------------------------------------------------------------

def test_get_default_verifiers():
    from verifiers import get_default_verifiers
    verifiers = get_default_verifiers()
    stages = {v.stage for v in verifiers}
    assert "cycle_consistency" in stages
    assert "factuality" in stages
    assert "applicability" in stages


def test_run_all_verifiers():
    from verifiers import run_all_verifiers
    from verification_record import VerificationSignal
    signals = run_all_verifiers(
        "使用 subprocess 时应设置 env 参数传递环境变量。",
        context="Python subprocess 环境变量设置",
    )
    assert len(signals) == 3
    for s in signals:
        assert isinstance(s, VerificationSignal)
        assert s.verdict in ("pass", "fail", "abstain")
