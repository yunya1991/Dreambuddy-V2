"""P2 T12 红测：BayesianVerifier 四条件门禁

测试用例：
  T12.1 test_verify_pass_when_calmar_improves_10pct   — Calmar 提升≥10% → 升级
  T12.2 test_verify_fail_when_calmar_no_improvement   — Calmar 无提升 → 回滚
  T12.3 test_verify_fail_when_dd_exceeds_60pct        — DD>60% → 回滚
  T12.4 test_verify_fail_when_hard_constraint_violated — 硬约束违例 → 回滚
  T12.5 test_verify_fail_when_ablation_significant    — 消融 p<0.05 显著退化 → 回滚

运行：
  python -m pytest 16-调控系统/scripts/param_center/tests/test_verifier.py -v
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 路径设置
_THIS = Path(__file__).resolve()
_PARAM_CENTER = _THIS.parent.parent
_SCRIPTS_16 = _PARAM_CENTER.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for p in [_YIJING_SCRIPTS, _SCRIPTS_16, _PARAM_CENTER]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# 导入被测对象（实现尚未编写 → RED）
from param_center.verifier import (  # noqa: E402
    BayesianVerifier,
    VerificationResult,
)
from param_center.aggregator import ParamProposal  # noqa: E402


def _make_proposal(sl=0.05, tp=0.15, atr=4.5, conf=0.8) -> ParamProposal:
    return ParamProposal(
        params={"sl_floor": sl, "tp_floor": tp, "atr_mult": atr},
        confidence=conf,
        weights={"test": 1.0},
    )


# ============================================================================
# T12.1 Calmar 提升≥10% → 升级
# ============================================================================
def test_verify_pass_when_calmar_improves_10pct():
    """新参数 Calmar = 旧×1.1+ → 门禁通过 → 升级"""
    verifier = BayesianVerifier()

    # mock 回测结果：新 Calmar=1.5, 旧 Calmar=1.0 (提升 50%)
    new_result = MagicMock(calmar=1.5, max_drawdown=0.3, win_rate=0.5)
    old_result = MagicMock(calmar=1.0, max_drawdown=0.4, win_rate=0.45)
    with patch.object(verifier, "_run_backtest", side_effect=[new_result, old_result]):
        with patch.object(verifier, "_run_ablation", return_value=(False, 0.3)):
            result = verifier.verify_and_upgrade(
                proposal=_make_proposal(),
                symbol="BTC",
            )
    assert result.passed, f"Calmar 提升 50% 应通过，回滚原因: {result.rollback_reason}"
    assert result.version_bumped


# ============================================================================
# T12.2 Calmar 无提升 → 回滚
# ============================================================================
def test_verify_fail_when_calmar_no_improvement():
    """新参数 Calmar = 旧×1.05 < 1.1 → 回滚"""
    verifier = BayesianVerifier()
    new_result = MagicMock(calmar=1.05, max_drawdown=0.3, win_rate=0.5)
    old_result = MagicMock(calmar=1.0, max_drawdown=0.4, win_rate=0.45)
    with patch.object(verifier, "_run_backtest", side_effect=[new_result, old_result]):
        with patch.object(verifier, "_run_ablation", return_value=(False, 0.3)):
            result = verifier.verify_and_upgrade(
                proposal=_make_proposal(),
                symbol="BTC",
            )
    assert not result.passed
    assert "Calmar" in (result.rollback_reason or "")


# ============================================================================
# T12.3 DD > 60% → 回滚
# ============================================================================
def test_verify_fail_when_dd_exceeds_60pct():
    """新参数最大回撤 0.7 > 0.6 → 回滚"""
    verifier = BayesianVerifier()
    new_result = MagicMock(calmar=2.0, max_drawdown=0.7, win_rate=0.5)  # DD 超标
    old_result = MagicMock(calmar=1.0, max_drawdown=0.4, win_rate=0.45)
    with patch.object(verifier, "_run_backtest", side_effect=[new_result, old_result]):
        with patch.object(verifier, "_run_ablation", return_value=(False, 0.3)):
            result = verifier.verify_and_upgrade(
                proposal=_make_proposal(),
                symbol="BTC",
            )
    assert not result.passed
    assert "回撤" in (result.rollback_reason or "") or "DD" in (result.rollback_reason or "")


# ============================================================================
# T12.4 硬约束违例 → 回滚
# ============================================================================
def test_verify_fail_when_hard_constraint_violated():
    """新参数 SL=0.02 < 0.03 → 硬约束违例 → 回滚"""
    verifier = BayesianVerifier()
    new_result = MagicMock(calmar=2.0, max_drawdown=0.3, win_rate=0.5)
    old_result = MagicMock(calmar=1.0, max_drawdown=0.4, win_rate=0.45)
    # proposal SL=0.02 违规
    bad_proposal = _make_proposal(sl=0.02, tp=0.05)
    with patch.object(verifier, "_run_backtest", side_effect=[new_result, old_result]):
        with patch.object(verifier, "_run_ablation", return_value=(False, 0.3)):
            result = verifier.verify_and_upgrade(
                proposal=bad_proposal,
                symbol="BTC",
            )
    assert not result.passed
    assert "硬约束" in (result.rollback_reason or "")


# ============================================================================
# T12.5 消融显著退化 → 回滚
# ============================================================================
def test_verify_fail_when_ablation_significant():
    """消融实验 p<0.05 显著退化 → 回滚"""
    verifier = BayesianVerifier()
    new_result = MagicMock(calmar=2.0, max_drawdown=0.3, win_rate=0.5)
    old_result = MagicMock(calmar=1.0, max_drawdown=0.4, win_rate=0.45)
    with patch.object(verifier, "_run_backtest", side_effect=[new_result, old_result]):
        # 消融显著退化 (significant=True, p=0.02 < 0.05)
        with patch.object(verifier, "_run_ablation", return_value=(True, 0.02)):
            result = verifier.verify_and_upgrade(
                proposal=_make_proposal(),
                symbol="BTC",
            )
    assert not result.passed
    assert "消融" in (result.rollback_reason or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
