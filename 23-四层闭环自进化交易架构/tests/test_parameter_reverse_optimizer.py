"""RED 测试：ParameterReverseOptimizer — 参数逆向优化。

P2 §5.3: 止损/止盈/超时参数的逆向优化
  - 若多次"方向对但被扫损"（CS≥0.7 & SL）→ 放宽止损
  - 若多次"方向对但超时" → 延长持仓时间
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))

from parameter_reverse_optimizer import ParameterReverseOptimizer


def _trade(cs, outcome, symbol="BTC"):
    return {"symbol": symbol, "cs": cs, "outcome": outcome}


def test_repeated_false_failure_widens_stop_loss():
    """RED: 多次方向对但被扫损(CS≥0.7&SL) → 放宽止损。"""
    opt = ParameterReverseOptimizer(false_failure_threshold=3)
    # 3 次假失败（方向对但被扫损）
    for _ in range(3):
        opt.record_trade(_trade(cs=0.8, outcome="SL"))

    adjustments = opt.optimize()

    assert "stop_loss_mult" in adjustments
    assert adjustments["stop_loss_mult"] > 1.0  # 放宽止损（乘数 > 1）


def test_repeated_timeout_extends_holding():
    """RED: 多次方向对但超时 → 延长持仓时间。"""
    opt = ParameterReverseOptimizer(timeout_threshold=3)
    for _ in range(3):
        opt.record_trade(_trade(cs=0.8, outcome="TIMEOUT"))

    adjustments = opt.optimize()

    assert "timeout_mult" in adjustments
    assert adjustments["timeout_mult"] > 1.0  # 延长持仓（乘数 > 1）


def test_below_threshold_no_adjustment():
    """RED: 样本不足阈值时不调整（冷启动保护）。"""
    opt = ParameterReverseOptimizer(false_failure_threshold=5)
    opt.record_trade(_trade(cs=0.8, outcome="SL"))  # 仅1次，不足阈值

    adjustments = opt.optimize()

    assert adjustments["stop_loss_mult"] == pytest.approx(1.0)


def test_true_failure_does_not_widen_stop_loss():
    """RED: 真失败(CS低&SL)不应放宽止损（方向错了，止损是对的）。"""
    opt = ParameterReverseOptimizer(false_failure_threshold=3)
    for _ in range(3):
        opt.record_trade(_trade(cs=-0.5, outcome="SL"))  # 真失败

    adjustments = opt.optimize()

    assert adjustments["stop_loss_mult"] == pytest.approx(1.0)


def test_adjustments_bounded():
    """RED: 参数调整有边界（防止过度调整）。"""
    opt = ParameterReverseOptimizer(
        false_failure_threshold=2, timeout_threshold=2,
        max_stop_loss_mult=2.0, max_timeout_mult=3.0,
    )
    # 大量假失败 + 超时
    for _ in range(10):
        opt.record_trade(_trade(cs=0.8, outcome="SL"))
        opt.record_trade(_trade(cs=0.8, outcome="TIMEOUT"))

    adjustments = opt.optimize()

    assert adjustments["stop_loss_mult"] <= opt._max_stop_loss_mult
    assert adjustments["timeout_mult"] <= opt._max_timeout_mult
