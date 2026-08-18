"""三屏趋势系统 — 绩效指标计算模块

参考 QuantConnect LEAN / 业界标准的绩效指标体系：
- 收益指标：年化收益、累计收益
- 风险指标：最大回撤、波动率、下行波动率
- 风险调整收益：夏普、索提诺、卡玛
- 交易统计：胜率、盈亏比、交易次数
- 一致性：月胜率、连续亏损
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np


def calculate_performance_metrics(
    equity: pd.Series,
    returns: pd.Series,
    trades: Optional[pd.DataFrame] = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365,
) -> Dict:
    """
    计算完整的绩效指标

    参数:
        equity: 净值曲线
        returns: 日收益率序列
        trades: 交易记录 DataFrame
        risk_free_rate: 无风险利率（年化）
        periods_per_year: 每年的期数（日线=365，小时线=365*24）

    返回:
        完整的绩效指标字典
    """
    metrics = {}

    metrics.update(_calc_return_metrics(equity, returns, periods_per_year))
    metrics.update(_calc_risk_metrics(equity, returns, periods_per_year))
    metrics.update(_calc_risk_adjusted_metrics(
        equity, returns, risk_free_rate, periods_per_year
    ))
    metrics.update(_calc_trade_metrics(trades))
    metrics.update(_calc_consistency_metrics(equity, returns, periods_per_year))

    return metrics


def _calc_return_metrics(
    equity: pd.Series, returns: pd.Series, periods_per_year: int
) -> Dict:
    """收益指标"""
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_periods = len(returns)
    years = n_periods / periods_per_year

    if years > 0:
        annualized_return = (1 + total_return) ** (1 / years) - 1
    else:
        annualized_return = 0.0

    return {
        "total_return_pct": round(total_return * 100, 2),
        "annualized_return_pct": round(annualized_return * 100, 2),
        "final_equity": round(equity.iloc[-1], 2),
        "initial_equity": round(equity.iloc[0], 2),
        "n_periods": n_periods,
        "years": round(years, 2),
        "total_trades": 0,
        "closed_trades": 0,
        "open_trades": 0,
    }


def _calc_risk_metrics(
    equity: pd.Series, returns: pd.Series, periods_per_year: int
) -> Dict:
    """风险指标"""
    daily_vol = returns.std()
    annualized_vol = daily_vol * np.sqrt(periods_per_year)

    negative_returns = returns[returns < 0]
    if len(negative_returns) > 0:
        downside_vol = negative_returns.std() * np.sqrt(periods_per_year)
    else:
        downside_vol = 0.0

    max_dd, max_dd_start, max_dd_peak, max_dd_trough = _max_drawdown(equity)

    var_95 = np.percentile(returns.dropna(), 5)
    cvar_95 = returns[returns <= var_95].mean() if len(returns[returns <= var_95]) > 0 else 0.0

    return {
        "annualized_volatility_pct": round(annualized_vol * 100, 2),
        "downside_volatility_pct": round(downside_vol * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "max_drawdown_start": max_dd_start,
        "max_drawdown_peak": round(max_dd_peak, 2) if max_dd_peak else None,
        "max_drawdown_trough": round(max_dd_trough, 2) if max_dd_trough else None,
        "var_95_pct": round(var_95 * 100, 2),
        "cvar_95_pct": round(cvar_95 * 100, 2),
    }


def _max_drawdown(equity: pd.Series):
    """计算最大回撤"""
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax

    max_dd = drawdown.min()

    if max_dd < 0:
        trough_idx = drawdown.idxmin()
        peak_idx = equity[:trough_idx].idxmax()
        peak_value = equity[peak_idx]
        trough_value = equity[trough_idx]
        return abs(max_dd), peak_idx, peak_value, trough_value

    return 0.0, None, None, None


def _calc_risk_adjusted_metrics(
    equity: pd.Series,
    returns: pd.Series,
    risk_free_rate: float,
    periods_per_year: int,
) -> Dict:
    """风险调整收益指标"""
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_periods = len(returns)
    years = n_periods / periods_per_year

    if years > 0:
        annualized_return = (1 + total_return) ** (1 / years) - 1
    else:
        annualized_return = 0.0

    daily_vol = returns.std()
    annualized_vol = daily_vol * np.sqrt(periods_per_year)

    if annualized_vol > 0:
        sharpe = (annualized_return - risk_free_rate) / annualized_vol
    else:
        sharpe = 0.0

    negative_returns = returns[returns < 0]
    if len(negative_returns) > 0:
        downside_vol = negative_returns.std() * np.sqrt(periods_per_year)
        sortino = (annualized_return - risk_free_rate) / downside_vol if downside_vol > 0 else 0.0
    else:
        sortino = 0.0

    max_dd, _, _, _ = _max_drawdown(equity)
    if max_dd > 0:
        calmar = annualized_return / max_dd
    else:
        calmar = 0.0

    return {
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
    }


def _calc_trade_metrics(trades: Optional[pd.DataFrame]) -> Dict:
    """交易统计指标"""
    if trades is None or len(trades) == 0:
        return {
            "total_trades": 0,
            "closed_trades": 0,
            "open_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl_pct": 0.0,
            "avg_win_pnl_pct": 0.0,
            "avg_loss_pnl_pct": 0.0,
            "best_trade_pct": 0.0,
            "worst_trade_pct": 0.0,
            "avg_holding_bars": 0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
        }

    if "open" in trades.columns:
        is_open = trades["open"].fillna(False).astype(bool)
        closed_trades = trades[~is_open]
        open_trades = trades[is_open]
        n_closed = len(closed_trades)
        n_open = len(open_trades)
    else:
        closed_trades = trades
        n_closed = len(trades)
        n_open = 0

    if n_closed == 0:
        return {
            "total_trades": len(trades),
            "closed_trades": 0,
            "open_trades": n_open,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl_pct": 0.0,
            "avg_win_pnl_pct": 0.0,
            "avg_loss_pnl_pct": 0.0,
            "best_trade_pct": 0.0,
            "worst_trade_pct": 0.0,
            "avg_holding_bars": 0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
        }

    wins = closed_trades[closed_trades["pnl_pct"] > 0]
    losses = closed_trades[closed_trades["pnl_pct"] <= 0]

    win_rate = len(wins) / n_closed
    total_win = wins["pnl_pct"].sum() if len(wins) > 0 else 0
    total_loss = abs(losses["pnl_pct"].sum()) if len(losses) > 0 else 0.001

    profit_factor = total_win / total_loss if total_loss > 0 else float("inf")

    return {
        "total_trades": len(trades),
        "closed_trades": n_closed,
        "open_trades": len(trades) - n_closed,
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_trade_pnl_pct": round(closed_trades["pnl_pct"].mean(), 2),
        "avg_win_pnl_pct": round(wins["pnl_pct"].mean(), 2) if len(wins) > 0 else 0.0,
        "avg_loss_pnl_pct": round(losses["pnl_pct"].mean(), 2) if len(losses) > 0 else 0.0,
        "best_trade_pct": round(closed_trades["pnl_pct"].max(), 2),
        "worst_trade_pct": round(closed_trades["pnl_pct"].min(), 2),
        "avg_holding_bars": round(closed_trades["holding_bars"].mean(), 1),
        "max_consecutive_wins": _max_consecutive(closed_trades["pnl_pct"] > 0),
        "max_consecutive_losses": _max_consecutive(closed_trades["pnl_pct"] <= 0),
    }


def _max_consecutive(series: pd.Series) -> int:
    """计算最大连续True的次数"""
    if len(series) == 0:
        return 0

    max_count = 0
    current = 0

    for val in series:
        if val:
            current += 1
            max_count = max(max_count, current)
        else:
            current = 0

    return max_count


def _calc_consistency_metrics(
    equity: pd.Series, returns: pd.Series, periods_per_year: int
) -> Dict:
    """一致性指标"""
    monthly_returns = pd.Series(dtype=float)

    if isinstance(equity.index, pd.DatetimeIndex) and periods_per_year >= 28:
        try:
            monthly_returns = equity.resample("ME").last().pct_change().dropna()
        except Exception:
            monthly_returns = pd.Series(dtype=float)

    if len(monthly_returns) > 0:
        positive_months = (monthly_returns > 0).sum()
        month_win_rate = positive_months / len(monthly_returns)
        n_pos = int((monthly_returns > 0).sum())
        n_neg = int((monthly_returns <= 0).sum())
    else:
        month_win_rate = 0.0
        n_pos = 0
        n_neg = 0

    return {
        "monthly_win_rate_pct": round(month_win_rate * 100, 2),
        "n_positive_months": n_pos,
        "n_negative_months": n_neg,
    }
