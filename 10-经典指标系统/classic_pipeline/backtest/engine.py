"""回测引擎（向量化）。

使用 classic_pipeline.signals 模块的纯函数进行回测，
保证回测-实盘一致性。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from classic_pipeline.core.utils import _sf0


def run_backtest(
    df: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame, Dict[str, Any]], Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    initial_capital: float = 10000.0,
) -> Dict[str, Any]:
    """运行向量化回测。

    Args:
        df: OHLCV DataFrame
        signal_fn: 信号函数（如 quant_signal.compute 或 three_screen.compute）
        config: 信号函数配置
        initial_capital: 初始资金

    Returns:
        {total_return, sharpe, max_drawdown, win_rate, n_trades, equity_curve}
    """
    cfg = config or {}
    if df is None or len(df) < 30:
        return {
            "total_return": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "n_trades": 0,
            "equity_curve": [],
        }

    try:
        closes = pd.to_numeric(df["close"], errors="coerce").tolist()
        n = len(closes)

        # 滚动生成信号（简化：每根 K 线用历史数据生成信号）
        signals: List[str] = []
        for i in range(20, n):
            window = df.iloc[: i + 1]
            try:
                result = signal_fn(window, cfg)
                direction = str(result.get("direction") or result.get("dominant_direction") or "neutral").lower()
                signals.append(direction)
            except Exception:
                signals.append("neutral")

        # 计算收益
        equity = initial_capital
        equity_curve: List[float] = [initial_capital]
        positions: List[str] = []  # "long", "short", "flat"
        trades: List[float] = []  # 每笔交易收益率

        current_pos = "flat"
        entry_price = 0.0

        for i, sig in enumerate(signals):
            price_idx = i + 20  # 对应 closes 的索引
            if price_idx >= n:
                break
            price = closes[price_idx]

            if current_pos == "flat":
                if sig in ("long", "short"):
                    current_pos = sig
                    entry_price = price
            elif current_pos == "long":
                if sig == "short" or sig == "neutral":
                    # 平仓
                    ret = (price - entry_price) / entry_price
                    trades.append(ret)
                    equity *= (1 + ret)
                    current_pos = "flat"
                    if sig == "short":
                        current_pos = "short"
                        entry_price = price
            elif current_pos == "short":
                if sig == "long" or sig == "neutral":
                    ret = (entry_price - price) / entry_price
                    trades.append(ret)
                    equity *= (1 + ret)
                    current_pos = "flat"
                    if sig == "long":
                        current_pos = "long"
                        entry_price = price

            equity_curve.append(equity)

        # 绩效指标
        total_return = (equity - initial_capital) / initial_capital if initial_capital > 0 else 0.0

        # 最大回撤
        peak = initial_capital
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # 胜率
        n_trades = len(trades)
        wins = sum(1 for t in trades if t > 0)
        win_rate = wins / n_trades if n_trades > 0 else 0.0

        # Sharpe（简化：用交易收益率的均值/标准差）
        if n_trades > 1:
            rets = np.array(trades)
            sharpe = float(np.mean(rets) / (np.std(rets) + 1e-9) * np.sqrt(252))
        else:
            sharpe = 0.0

        return {
            "total_return": float(total_return),
            "sharpe": float(sharpe),
            "max_drawdown": float(max_dd),
            "win_rate": float(win_rate),
            "n_trades": n_trades,
            "equity_curve": equity_curve,
        }
    except Exception:
        return {
            "total_return": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "n_trades": 0,
            "equity_curve": [],
        }


def walk_forward(
    df: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame, Dict[str, Any]], Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    window_size: int = 200,
    step_size: int = 50,
) -> List[Dict[str, Any]]:
    """Walk-Forward 分析。

    滚动窗口回测，评估策略稳定性。

    Args:
        df: OHLCV DataFrame
        signal_fn: 信号函数
        config: 配置
        window_size: 窗口大小
        step_size: 步长

    Returns:
        每个窗口的回测结果列表
    """
    results: List[Dict[str, Any]] = []
    if df is None or len(df) < window_size:
        return results

    for start in range(0, len(df) - window_size, step_size):
        window = df.iloc[start : start + window_size]
        result = run_backtest(window, signal_fn, config)
        results.append(result)

    return results
