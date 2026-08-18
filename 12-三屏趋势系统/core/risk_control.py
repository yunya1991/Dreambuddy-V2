"""三屏趋势系统 — 极端行情应对机制

Phase 2.3: 在策略层面增加风控层，包括：
1. 波动率突变检测：ATR > 2倍均值 → 极端行情降仓
2. 单日亏损熔断：日亏损 > 8% → 强制清仓
3. 最大回撤熔断：回撤 > 20% → 强制降仓
4. 流动性检测：成交量异常萎缩 → 不开新仓
"""

import numpy as np
import pandas as pd

try:
    import sys

    sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统")
    from talib import abstract as ta

    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False

try:
    from .config import (
        DAILY_LOSS_CIRCUIT_BREAKER,
        EXTREME_VOLATILITY_POSITION_CAP,
        EXTREME_VOLATILITY_THRESHOLD,
        MAX_DRAWDOWN_CIRCUIT_BREAKER,
    )
except ImportError:
    from config import (
        DAILY_LOSS_CIRCUIT_BREAKER,
        EXTREME_VOLATILITY_POSITION_CAP,
        EXTREME_VOLATILITY_THRESHOLD,
        MAX_DRAWDOWN_CIRCUIT_BREAKER,
    )


class ExtremeMarketGuard:
    """极端行情风控守卫

    在策略生成信号后，对仓位进行风控调整：
    - 波动率飙升 → 仓位上限降至30%
    - 单日亏损 > 8% → 清仓冷却
    - 最大回撤 > 20% → 仓位减半
    - 成交量萎缩 > 50% → 不开新仓
    """

    def __init__(self):
        self.cooldown_remaining = 0  # 熔断冷却期（天数）
        self.peak_equity = 0.0  # 历史净值峰值

    def check(
        self,
        position: float,
        df: pd.DataFrame,
        idx: int,
        current_equity: float,
        prev_equity: float,
    ) -> tuple:
        """
        风控检查

        参数:
            position: 原始目标仓位
            df: OHLCV DataFrame
            idx: 当前时间索引
            current_equity: 当前净值
            prev_equity: 上一期净值

        返回:
            (adjusted_position, reason) — 调整后仓位和调整原因
        """
        if idx < 30 or not TALIB_AVAILABLE:
            return position, None

        reasons = []

        # 1. 熔断冷却期检查
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            return 0.0, f"熔断冷却中（剩余{self.cooldown_remaining}天）"

        # 更新净值峰值
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # 2. 波动率突变检测
        atr = ta.ATR(high, low, close, timeperiod=14)
        if len(atr) > 30 and not np.isnan(atr.iloc[idx]):
            atr_current = atr.iloc[idx]
            atr_mean = atr.iloc[idx - 30 : idx].mean()
            if atr_mean > 0:
                atr_ratio = atr_current / atr_mean

                if atr_ratio > EXTREME_VOLATILITY_THRESHOLD:
                    # 极端波动 → 仓位上限30%
                    capped = min(abs(position), EXTREME_VOLATILITY_POSITION_CAP)
                    if abs(position) > capped:
                        position = capped * (1 if position > 0 else -1)
                        reasons.append(f"极端波动(ATR×{atr_ratio:.1f})降仓至{capped:.0%}")

        # 3. 单日亏损熔断
        if prev_equity > 0:
            daily_loss = (current_equity - prev_equity) / prev_equity
            if daily_loss < -DAILY_LOSS_CIRCUIT_BREAKER:
                self.cooldown_remaining = 3  # 3天冷却
                return 0.0, f"单日亏损{daily_loss:.1%}触发熔断，3天冷却"

        # 4. 最大回撤熔断
        if self.peak_equity > 0:
            drawdown = (current_equity - self.peak_equity) / self.peak_equity
            if drawdown < -MAX_DRAWDOWN_CIRCUIT_BREAKER:
                # 回撤>20% → 仓位减半
                halved = position * 0.5
                if abs(halved) < abs(position):
                    position = halved
                    reasons.append(f"回撤{drawdown:.1%}>20%降仓50%")

        # 5. 流动性检测：成交量异常萎缩
        if idx >= 20:
            vol_current = volume.iloc[idx]
            vol_mean = volume.iloc[idx - 20 : idx].mean()
            if vol_mean > 0 and vol_current < vol_mean * 0.3:
                # 成交量萎缩>70% → 不开新仓（只允许减仓/平仓）
                if position != 0:
                    pass  # 保持已有仓位
                else:
                    reasons.append("流动性不足(成交量萎缩>70%)不开新仓")

        reason = "; ".join(reasons) if reasons else None
        return position, reason

    def reset(self):
        """重置状态"""
        self.cooldown_remaining = 0
        self.peak_equity = 0.0


def apply_risk_control(
    signals: pd.Series,
    df: pd.DataFrame,
    initial_capital: float = 10000.0,
) -> tuple:
    """
    对信号序列应用极端行情风控

    参数:
        signals: 原始目标仓位序列
        df: OHLCV DataFrame
        initial_capital: 初始资金

    返回:
        (adjusted_signals, risk_events) — 调整后信号和风控事件列表
    """
    guard = ExtremeMarketGuard()
    adjusted = signals.copy()
    events = []

    equity = initial_capital
    prev_equity = initial_capital

    for i in range(len(signals)):
        if i > 0:
            close = df["close"]
            ret = (close.iloc[i] - close.iloc[i - 1]) / close.iloc[i - 1] if i > 0 else 0
            equity = prev_equity * (1 + ret * adjusted.iloc[i - 1])

        original = adjusted.iloc[i]
        adj_pos, reason = guard.check(original, df, i, equity, prev_equity)

        if reason:
            adjusted.iloc[i] = adj_pos
            events.append(
                {
                    "idx": i,
                    "date": df.index[i] if isinstance(df.index, pd.DatetimeIndex) else i,
                    "original": round(original, 4),
                    "adjusted": round(adj_pos, 4),
                    "reason": reason,
                }
            )

        prev_equity = equity

    return adjusted, events
