"""RED 测试：回测验证 — 逆向推导启用后胜率提升。

P3: 模拟交易场景，对比启用/不启用逆向推导（因子权重调整）的胜率。
当某维度持续判断错时，逆向推导降权该维度因子 → 后续交易胜率提升。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))

from reverse_deriver import ReverseDeriver
from reverse_backtest import ReverseDerivationBacktest


def test_reverse_derivation_improves_win_rate():
    """RED: 启用逆向推导后胜率应高于不启用。

    场景: C1 维度持续判断错（噪声大），逆向推导降权 C1 因子后，
    决策更依赖准确的 C2/C3，胜率提升。
    """
    rng = np.random.RandomState(42)
    backtest = ReverseDerivationBacktest(rng=rng)

    # 不启用逆向推导
    result_no = backtest.run(enable_reverse=False, n_trades=200)
    # 启用逆向推导
    result_yes = backtest.run(enable_reverse=True, n_trades=200)

    assert result_yes["win_rate"] > result_no["win_rate"], (
        f"启用逆向推导胜率 {result_yes['win_rate']:.2%} 应高于 "
        f"不启用 {result_no['win_rate']:.2%}"
    )


def test_reverse_derivation_reduces_wrong_dim_impact():
    """RED: 启用逆向推导后错误维度的因子权重应降低。"""
    rng = np.random.RandomState(42)
    backtest = ReverseDerivationBacktest(rng=rng)

    result = backtest.run(enable_reverse=True, n_trades=100)

    # C1 是噪声维度，其权重应被降权
    c1_weight = result["final_weights"].get("C1", 1.0)
    assert c1_weight < 1.0, f"噪声维度 C1 权重应被降权，实际 {c1_weight}"


def test_backtest_returns_complete_metrics():
    """RED: 回测结果包含完整指标。"""
    rng = np.random.RandomState(42)
    backtest = ReverseDerivationBacktest(rng=rng)
    result = backtest.run(enable_reverse=True, n_trades=50)

    assert "win_rate" in result
    assert "total_trades" in result
    assert "wins" in result
    assert "losses" in result
    assert "final_weights" in result
    assert 0.0 <= result["win_rate"] <= 1.0
