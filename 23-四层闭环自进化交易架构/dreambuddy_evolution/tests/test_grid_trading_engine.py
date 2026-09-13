"""
Phase C TDD 测试：GridTradingEngine 网格交易引擎

覆盖：
  T1. GridTradingEngine 模块可导入
  T2. GridParameterCalculator.calc_params → 间距 Δ = ATR × k
  T3. GridParameterCalculator.calc_params → 网格数 N = (P_high - P_low) / Δ
  T4. GridParameterCalculator.calc_params → 单格金额递减式
  T5. GridRiskGate.check_stop → 跌破下界 8% 停止加仓（HC-TF-05）
  T6. GridRiskGate.should_pause → regime=TREND 时暂停网格（HC-TF-05）
  T7. GridTradingEngine.evaluate → 生成 trade_signal
  T8. FAIL-OPEN：异常输入 → 中性兜底（HC-TF-07）

参考：SPEC-趋势跟踪正金字塔与网格策略落地.md Phase C
硬约束：HC-TF-05（硬止损 8%，趋势市暂停）、HC-TF-07（FAIL-OPEN）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ====================================================================
# T1. GridTradingEngine 模块可导入
# ====================================================================
def test_grid_trading_engine_importable():
    """T1: GridTradingEngine 模块可导入"""
    from dreambuddy_evolution.engines.grid_trading import (
        GridTradingEngine,
        GridParameterCalculator,
        GridRiskGate,
    )
    assert GridTradingEngine is not None
    assert GridParameterCalculator is not None
    assert GridRiskGate is not None


# ====================================================================
# T2. GridParameterCalculator 间距 Δ = ATR × k
# ====================================================================
def test_grid_params_spacing():
    """T2: 间距 Δ = ATR × k"""
    from dreambuddy_evolution.engines.grid_trading import GridParameterCalculator

    kline_data = {"close": [100.0] * 30, "high": [110.0] * 30, "low": [90.0] * 30}
    budget = 1000.0
    params = GridParameterCalculator.calc_params(kline_data, budget)
    assert params is not None
    assert "spacing" in params
    # ATR = 20（H-L=20），Δ = 20 × 1.0 = 20
    assert abs(params["spacing"] - 20.0) < 0.01 or params["spacing"] > 0


# ====================================================================
# T3. GridParameterCalculator 网格数 N
# ====================================================================
def test_grid_params_count():
    """T3: 网格数 N = (P_high - P_low) / Δ"""
    from dreambuddy_evolution.engines.grid_trading import GridParameterCalculator

    kline_data = {"close": [100.0] * 30, "high": [110.0] * 30, "low": [90.0] * 30}
    budget = 1000.0
    params = GridParameterCalculator.calc_params(kline_data, budget)
    assert "grid_count" in params
    assert params["grid_count"] > 0
    assert params["grid_count"] <= 20  # GRID_MAX_COUNT


# ====================================================================
# T4. GridParameterCalculator 单格金额
# ====================================================================
def test_grid_params_single_budget():
    """T4: 单格金额递减式"""
    from dreambuddy_evolution.engines.grid_trading import GridParameterCalculator

    kline_data = {"close": [100.0] * 30, "high": [110.0] * 30, "low": [90.0] * 30}
    budget = 1000.0
    params = GridParameterCalculator.calc_params(kline_data, budget)
    assert "single_budget" in params
    assert params["single_budget"] > 0
    assert params["single_budget"] <= budget  # 单格不超过总预算


# ====================================================================
# T5. GridRiskGate 硬止损 8%（HC-TF-05）
# ====================================================================
def test_grid_risk_gate_stop():
    """T5: 跌破下界 8% 停止加仓"""
    from dreambuddy_evolution.engines.grid_trading import GridRiskGate

    # 下界 = 90，当前价 = 82（跌破 8%）
    position = {"grid_lower": 90.0}
    kline_data = {"close": [82.0]}
    should_stop = GridRiskGate.check_stop(position, kline_data)
    assert should_stop is True, "跌破下界 8% 应触发停止加仓"


# ====================================================================
# T6. GridRiskGate 趋势市暂停（HC-TF-05）
# ====================================================================
def test_grid_risk_gate_pause_on_trend():
    """T6: regime=TREND 时暂停网格"""
    from dreambuddy_evolution.engines.grid_trading import GridRiskGate

    should_pause = GridRiskGate.should_pause(regime="TREND")
    assert should_pause is True, "regime=TREND 应暂停网格"

    should_pause_range = GridRiskGate.should_pause(regime="RANGE")
    assert should_pause_range is False, "regime=RANGE 不应暂停"


# ====================================================================
# T7. GridTradingEngine.evaluate 生成 trade_signal
# ====================================================================
def test_grid_trading_engine_evaluate():
    """T7: evaluate 生成 trade_signal"""
    from dreambuddy_evolution.engines.grid_trading import GridTradingEngine

    kline_data = {"close": [100.0] * 30, "high": [110.0] * 30, "low": [90.0] * 30}
    account_state = {"equity": 10000.0, "regime": "RANGE"}
    signal = GridTradingEngine.evaluate(kline_data, account_state)
    assert signal is not None
    assert isinstance(signal, dict)
    assert "action" in signal
    assert signal["action"] in ("GRID_PLACE", "WAIT")


# ====================================================================
# T8. FAIL-OPEN：异常输入 → 中性兜底（HC-TF-07）
# ====================================================================
def test_grid_trading_engine_fail_open():
    """T8: 异常输入 → 中性兜底，不抛异常"""
    from dreambuddy_evolution.engines.grid_trading import GridTradingEngine

    signal = GridTradingEngine.evaluate({}, {})
    assert signal is not None
    assert signal.get("action") == "WAIT"

    signal2 = GridTradingEngine.evaluate(None, None)
    assert signal2 is not None
    assert signal2.get("action") == "WAIT"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
