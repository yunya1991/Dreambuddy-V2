"""WashoutTriggerGate — 洗盘判定触发门.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §4.3

触发条件（全部满足才激活）：
  1. 过去 N 天（默认 30d）内涨幅 >= min_runup_pct（默认 0.15，即 15%）
     —— 涨幅 = (peak_Nd - start_Nd) / start_Nd，从窗口起点到峰值
  2. 当前价格较 N 天高点回撤 >= min_drawdown_from_high（默认 0.05，即 5%）
  3. 价格仍在 MA200 之上（避免熊市假信号，require_above_ma200=True 时）

FAIL-OPEN: 任何异常 → 返回 False（不触发），绝不阻塞交易。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

__all__ = ["WashoutTriggerGate"]


class WashoutTriggerGate:
    """洗盘判定触发门：仅在「上涨后回调」场景激活，非全程运行。"""

    def __init__(
        self,
        min_runup_pct: float = 0.15,
        min_drawdown_from_high: float = 0.05,
        runup_lookback_days: int = 30,
        require_above_ma200: bool = True,
    ):
        self.min_runup_pct = float(min_runup_pct)
        self.min_drawdown_from_high = float(min_drawdown_from_high)
        self.runup_lookback_days = int(runup_lookback_days)
        self.require_above_ma200 = bool(require_above_ma200)

    def should_activate(self, df: pd.DataFrame) -> bool:
        """检测是否满足触发条件。

        Args:
            df: OHLCV DataFrame，至少有 close/high 列，长度 >= runup_lookback_days+1。

        Returns:
            True 如果满足「上涨后回调 + 价格在 MA200 之上」三个条件。
            任何异常 → False（FAIL-OPEN，不阻塞）。
        """
        try:
            if df is None:
                return False
            if not isinstance(df, pd.DataFrame):
                return False
            if len(df) < self.runup_lookback_days + 1:
                return False
            if "close" not in df.columns or "high" not in df.columns:
                return False

            close = df["close"].astype(float)
            high = df["high"].astype(float)
            n = len(df)
            lookback = self.runup_lookback_days

            # 30 天前的 close（窗口起点）
            start_price = float(close.iloc[-(lookback + 1)])
            if start_price <= 0:
                return False

            # 30 天窗口内的最高 high
            high_window = high.iloc[-lookback:]
            peak = float(high_window.max())
            if peak <= 0:
                return False

            # 当前 close
            end_price = float(close.iloc[-1])

            # 条件 1: 涨幅 = (peak - start) / start >= 15%
            runup = peak / start_price - 1.0
            if runup < self.min_runup_pct:
                return False

            # 条件 2: 回撤 = 1 - end/peak >= 5%
            if peak <= 0:
                return False
            drawdown = 1.0 - end_price / peak
            if drawdown < self.min_drawdown_from_high:
                return False

            # 条件 3: 价格在 MA200 之上（可选）
            if self.require_above_ma200:
                if n < 200:
                    return False
                ma200 = close.rolling(200, min_periods=100).mean().iloc[-1]
                if pd.isna(ma200) or end_price <= float(ma200):
                    return False

            return True
        except Exception:
            return False
