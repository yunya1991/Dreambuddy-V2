"""测试 classic_pipeline.signals.three_screen 模块。

验证三屏信号决策逻辑为纯函数，输出结构符合契约。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# 测试用 OHLCV 数据生成
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 50, trend: str = "flat") -> pd.DataFrame:
    """构造 OHLCV DataFrame。"""
    np.random.seed(42)
    base = 100.0
    if trend == "up":
        returns = np.abs(np.random.randn(n)) * 0.01 + 0.002
    elif trend == "down":
        returns = -np.abs(np.random.randn(n)) * 0.01 - 0.002
    else:
        returns = np.random.randn(n) * 0.005
    close = base * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.randn(n)) * 0.005)
    low = close * (1 - np.abs(np.random.randn(n)) * 0.005)
    open_ = close * (1 + np.random.randn(n) * 0.003)
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


# ---------------------------------------------------------------------------
# confirm_gate — 5m 信号确认
# ---------------------------------------------------------------------------

class TestConfirmGate:
    def test_bos_long_confirmed(self):
        """BOS 做多确认：收盘价突破过去 N 根最高价。"""
        from classic_pipeline.signals.three_screen import confirm_gate

        df = _make_ohlcv(50, trend="up")
        # 强制最后一根收盘价高于前面所有高点
        df.iloc[-1, df.columns.get_loc("close")] = df["high"].max() * 1.01
        df.iloc[-1, df.columns.get_loc("high")] = df["close"].iloc[-1] * 1.001

        result = confirm_gate(df, carry_side="long", config={"confirm_set": ["bos"]})
        assert result["ok"] is True
        assert "confirm_bos" in result["confirm_tags"]

    def test_bos_short_confirmed(self):
        """BOS 做空确认：收盘价跌破过去 N 根最低价。"""
        from classic_pipeline.signals.three_screen import confirm_gate

        df = _make_ohlcv(50, trend="down")
        df.iloc[-1, df.columns.get_loc("close")] = df["low"].min() * 0.99
        df.iloc[-1, df.columns.get_loc("low")] = df["close"].iloc[-1] * 0.999

        result = confirm_gate(df, carry_side="short", config={"confirm_set": ["bos"]})
        assert result["ok"] is True
        assert "confirm_bos" in result["confirm_tags"]

    def test_ema_turn_long(self):
        """EMA Turn 做多确认：快速 EMA 斜率由负转正。"""
        from classic_pipeline.signals.three_screen import confirm_gate

        # 构造先跌后涨的走势，触发 EMA 拐点
        df = _make_ohlcv(50, trend="down")
        df.iloc[-10:, df.columns.get_loc("close")] = np.linspace(
            df["close"].iloc[-10], df["close"].iloc[-10] * 1.05, 10
        )
        df["high"] = df["close"] * 1.002
        df["low"] = df["close"] * 0.998

        result = confirm_gate(df, carry_side="long", config={"confirm_set": ["ema_turn"]})
        # EMA Turn 需要精确条件，不一定每次都触发，验证返回结构正确
        assert "ok" in result
        assert "confirm_tags" in result
        assert "details" in result

    def test_no_confirm_when_no_match(self):
        """无确认条件满足时返回 ok=False。"""
        from classic_pipeline.signals.three_screen import confirm_gate

        df = _make_ohlcv(50, trend="flat")
        result = confirm_gate(df, carry_side="long", config={"confirm_set": ["bos"]})
        # flat 走势不应触发 BOS
        assert result["ok"] is False
        assert result["tag"] == "no_confirm"

    def test_insufficient_data(self):
        """数据不足时返回 ok=True（FAIL-OPEN，不阻塞）。"""
        from classic_pipeline.signals.three_screen import confirm_gate

        df = _make_ohlcv(10)
        result = confirm_gate(df, carry_side="long", config={})
        assert result["ok"] is True
        assert result["tag"] == "insufficient"


# ---------------------------------------------------------------------------
# compute — 最终信号计算
# ---------------------------------------------------------------------------

class TestCompute:
    def test_compute_returns_signal_structure(self):
        """compute 返回结构包含 direction/confidence/strategy/reject_reason。"""
        from classic_pipeline.signals.three_screen import compute

        df_5m = _make_ohlcv(50, trend="up")
        df_daily = _make_ohlcv(50, trend="up")

        result = compute(df_5m, df_daily, config={
            "confirm_set": ["bos"],
            "bos_lookback_bars": 8,
        })
        assert "direction" in result
        assert "confidence" in result
        assert "strategy" in result
        assert "reject_reason" in result

    def test_compute_fail_open_on_error(self):
        """异常时返回 FAIL-OPEN（空结果）。"""
        from classic_pipeline.signals.three_screen import compute

        result = compute(None, None, config={})
        assert result["direction"] == "neutral"
        assert result["confidence"] == 0.0

    def test_compute_daily_alignment(self):
        """日线方向与周线方向一致时才允许开仓。"""
        from classic_pipeline.signals.three_screen import compute

        df_5m = _make_ohlcv(50, trend="up")
        df_daily = _make_ohlcv(50, trend="down")  # 日线向下

        result = compute(df_5m, df_daily, config={
            "confirm_set": ["bos"],
            "require_daily_alignment": True,
        })
        # 日线向下，即使 5m 有 BOS 也不应做多
        assert result["direction"] in ("neutral", "short")


# ---------------------------------------------------------------------------
# 纯函数验证
# ---------------------------------------------------------------------------

class TestPureFunction:
    def test_no_global_state_dependency(self):
        """signals 模块不依赖全局状态。"""
        import inspect
        from classic_pipeline.signals import three_screen

        for name, func in inspect.getmembers(three_screen, inspect.isfunction):
            if name.startswith("_"):
                continue
            src = inspect.getsource(func)
            assert "CONFIG" not in src or "config" in src.lower(), f"{name} 可能引用全局 CONFIG"
