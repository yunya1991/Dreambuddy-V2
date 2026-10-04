"""测试 classic_pipeline.backtest 模块。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    np.random.seed(42)
    n = 100
    base = 100.0
    returns = np.random.randn(n) * 0.01
    close = base * np.cumprod(1 + returns)
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })


class TestRunBacktest:
    def test_returns_metrics(self, ohlcv_df):
        from classic_pipeline.backtest import run_backtest
        from classic_pipeline.signals.quant_signal import compute

        result = run_backtest(ohlcv_df, compute, config={})
        assert "total_return" in result
        assert "sharpe" in result
        assert "max_drawdown" in result
        assert "win_rate" in result
        assert "n_trades" in result
        assert "equity_curve" in result

    def test_insufficient_data(self):
        from classic_pipeline.backtest import run_backtest
        from classic_pipeline.signals.quant_signal import compute

        df = pd.DataFrame({"close": [100, 101]})
        result = run_backtest(df, compute, config={})
        assert result["n_trades"] == 0

    def test_equity_curve_non_empty(self, ohlcv_df):
        from classic_pipeline.backtest import run_backtest
        from classic_pipeline.signals.quant_signal import compute

        result = run_backtest(ohlcv_df, compute, config={})
        assert len(result["equity_curve"]) > 0
        assert result["equity_curve"][0] == 10000.0


class TestWalkForward:
    def test_returns_list(self, ohlcv_df):
        from classic_pipeline.backtest import walk_forward
        from classic_pipeline.signals.quant_signal import compute

        results = walk_forward(ohlcv_df, compute, config={}, window_size=50, step_size=20)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "total_return" in r

    def test_insufficient_data(self):
        from classic_pipeline.backtest import walk_forward
        from classic_pipeline.signals.quant_signal import compute

        df = pd.DataFrame({"close": [100, 101]})
        results = walk_forward(df, compute, config={})
        assert results == []
