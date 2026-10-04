"""测试 classic_pipeline.indicators 模块。

验证指标函数为纯函数（输入 DataFrame，输出 Series），不依赖全局状态。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# 测试用 OHLCV DataFrame
# ---------------------------------------------------------------------------

@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """构造 100 根 K 线的 OHLCV DataFrame。"""
    np.random.seed(42)
    n = 100
    base = 100.0
    returns = np.random.randn(n) * 0.02
    close = base * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.randn(n)) * 0.01)
    low = close * (1 - np.abs(np.random.randn(n)) * 0.01)
    open_ = close * (1 + np.random.randn(n) * 0.005)
    volume = np.random.randint(1000, 10000, n).astype(float)
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ---------------------------------------------------------------------------
# trend.py — 趋势指标
# ---------------------------------------------------------------------------

class TestTrendIndicators:
    def test_ema_returns_series(self, ohlcv_df):
        from classic_pipeline.indicators.trend import ema
        result = ema(ohlcv_df, period=20)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_ema_smooths_close(self, ohlcv_df):
        from classic_pipeline.indicators.trend import ema
        result = ema(ohlcv_df, period=20)
        # EMA 不应全等于 close（有平滑效果）
        assert not result.equals(ohlcv_df["close"])
        # EMA 长度应与输入一致
        assert len(result) == len(ohlcv_df)

    def test_sma_returns_series(self, ohlcv_df):
        from classic_pipeline.indicators.trend import sma
        result = sma(ohlcv_df, period=20)
        assert isinstance(result, pd.Series)

    def test_adx_returns_series(self, ohlcv_df):
        from classic_pipeline.indicators.trend import adx
        result = adx(ohlcv_df, period=14)
        assert isinstance(result, pd.Series)

    def test_macd_returns_dataframe(self, ohlcv_df):
        from classic_pipeline.indicators.trend import macd
        result = macd(ohlcv_df, fast=12, slow=26, signal=9)
        # MACD 返回 DataFrame（macd, signal, histogram 三列）
        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"macd", "signal", "histogram"}


# ---------------------------------------------------------------------------
# momentum.py — 动量指标
# ---------------------------------------------------------------------------

class TestMomentumIndicators:
    def test_rsi_returns_series(self, ohlcv_df):
        from classic_pipeline.indicators.momentum import rsi
        result = rsi(ohlcv_df, period=14)
        assert isinstance(result, pd.Series)
        # RSI 值域 [0, 100]
        assert result.dropna().between(0, 100).all()

    def test_rsi_range(self, ohlcv_df):
        from classic_pipeline.indicators.momentum import rsi
        result = rsi(ohlcv_df, period=14)
        values = result.dropna()
        assert (values >= 0).all() and (values <= 100).all()

    def test_cci_returns_series(self, ohlcv_df):
        from classic_pipeline.indicators.momentum import cci
        result = cci(ohlcv_df, period=14)
        assert isinstance(result, pd.Series)

    def test_stoch_returns_dataframe(self, ohlcv_df):
        from classic_pipeline.indicators.momentum import stoch
        result = stoch(ohlcv_df, fastk=14, slowk=3, slowd=3)
        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"slowk", "slowd"}


# ---------------------------------------------------------------------------
# volatility.py — 波动率指标
# ---------------------------------------------------------------------------

class TestVolatilityIndicators:
    def test_atr_returns_series(self, ohlcv_df):
        from classic_pipeline.indicators.volatility import atr
        result = atr(ohlcv_df, period=14)
        assert isinstance(result, pd.Series)
        # ATR 应为非负
        assert (result.dropna() >= 0).all()

    def test_boll_returns_dataframe(self, ohlcv_df):
        from classic_pipeline.indicators.volatility import boll
        result = boll(ohlcv_df, period=20, nbdev=2.0)
        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"upper", "middle", "lower"}

    def test_boll_upper_above_lower(self, ohlcv_df):
        from classic_pipeline.indicators.volatility import boll
        result = boll(ohlcv_df, period=20, nbdev=2.0)
        valid = result.dropna()
        assert (valid["upper"] >= valid["lower"]).all()


# ---------------------------------------------------------------------------
# TR-2.1: 纯函数验证（不依赖全局状态）
# ---------------------------------------------------------------------------

class TestPureFunction:
    def test_no_global_state_dependency(self, ohlcv_df):
        """指标函数不依赖 CONFIG/UNIVERSE_STATE/锁等全局状态。"""
        import inspect
        from classic_pipeline.indicators import trend, momentum, volatility

        for module in [trend, momentum, volatility]:
            for name, func in inspect.getmembers(module, inspect.isfunction):
                if name.startswith("_"):
                    continue
                src = inspect.getsource(func)
                assert "CONFIG" not in src, f"{name} 引用了 CONFIG"
                assert "UNIVERSE_STATE" not in src, f"{name} 引用了 UNIVERSE_STATE"
                assert "_LOCK" not in src, f"{name} 引用了 _LOCK"
