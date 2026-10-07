#!/usr/bin/env python3
"""三维分类 SL/TP 贝叶斯参数优化器

针对每个 (asset_class, market_cap_tier) 组合，用历史 K 线回测优化：
  - sl_floor:  0.04 - 0.10
  - tp_floor:  0.12 - 0.30
  - atr_mult:  3.0  - 6.0

约束：RR≥2:1, 胜率≥40%, 最大回撤≤60%
目标：最大化 Calmar ratio（年化收益 / |最大回撤|）

用法：
  python sltp_bayesian_optimizer.py --symbol BTC --n-iter 30
  python sltp_bayesian_optimizer.py --all --n-iter 20
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from bayes_opt import BayesianOptimization
except ImportError:
    raise ImportError("需要安装 bayesian-optimization: pip install bayesian-optimization")

# 路径设置
_THIS_DIR = Path(__file__).resolve().parent
_MEMORY_L4 = _THIS_DIR.parent
_SCRIPTS = _MEMORY_L4.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from memory_l4.bcrm2.asset_classifier import classify_asset
from memory_l4.bcrm2.sl_tp_config import get_sltp_params, SLTPParams

logger = logging.getLogger(__name__)

# K 线数据目录
KLINES_DIR = _SCRIPTS / "data" / "klines"

# 回测参数
FEE_PCT = 0.001       # 单边手续费 0.1%
LEVERAGE = 1.0        # 回测用无杠杆（关注 SL/TP 本身的效果）
POSITION_PCT = 0.10   # 每次开仓用 10% 资金
TRADE_INTERVAL = 24   # 每 24 根 K 线开一次仓（1H = 每天一次）
MAX_HOLD_BARS = 168   # 最大持仓 168 根 K 线（1H = 7 天）


@dataclass
class BacktestResult:
    """回测结果"""
    total_trades: int
    win_rate: float
    avg_rr: float
    total_return: float
    max_drawdown: float
    calmar: float
    sharpe: float
    params: Dict[str, float]


def load_klines(symbol: str, timeframe: str = "1H") -> Optional[pd.DataFrame]:
    """加载 K 线数据"""
    path = KLINES_DIR / f"{symbol}_{timeframe}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def compute_atr(closes: np.ndarray, high: np.ndarray, low: np.ndarray, period: int = 14) -> np.ndarray:
    """计算 ATR（百分比形式）"""
    n = len(closes)
    atr_pct = np.zeros(n)
    if n < period + 2:
        return atr_pct
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - closes[:-1]),
            np.abs(low[1:] - closes[:-1]),
        ),
    )
    # rolling mean，前 period-1 个为 NaN
    atr_series = pd.Series(tr).rolling(period).mean().values  # shape (n-1,)
    # atr_series[i] 对应 closes[i+1] 的 ATR
    atr_pct[1:] = atr_series / closes[1:]
    return np.nan_to_num(atr_pct, nan=0.0)


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    sl_floor: float,
    tp_floor: float,
    atr_mult: float,
    regime: str = "chop",
) -> BacktestResult:
    """对单个币种运行回测

    开仓策略：每 TRADE_INTERVAL 根 K 线开一次多仓
    平仓条件：SL 触发 / TP 触发 / 达到最大持仓时间
    """
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    n = len(closes)

    # 获取资产分类
    asset_class, mcap_tier = classify_asset(symbol)

    # 从参数表获取基础参数（覆盖 sl_floor, tp_floor, atr_mult）
    base_params = get_sltp_params(asset_class, mcap_tier, regime)

    atr_pct = compute_atr(closes, highs, lows, period=14)

    # MA200 趋势过滤
    ma200 = pd.Series(closes).rolling(200).mean().values

    trades: List[float] = []  # 每笔交易的组合收益率
    equity = 1.0
    equity_curve = [1.0]

    i = 250  # 跳过前 250 根（确保 MA200 和 ATR 有足够数据）
    while i < n - 1:
        # 趋势方向判断：close > MA200 → 做多，close < MA200 → 做空
        if np.isnan(ma200[i]):
            i += TRADE_INTERVAL
            continue
        if closes[i] > ma200[i]:
            direction = 1   # 做多
        else:
            direction = -1  # 做空

        # 开仓
        entry_px = closes[i]
        atr = atr_pct[i] if atr_pct[i] > 0 else 0.01

        # 计算 SL/TP
        sl_pct = max(atr_mult * atr, sl_floor)
        sl_pct = min(sl_pct, 0.15)
        tp_pct = max(sl_pct * 3.0, tp_floor)
        tp_pct = min(tp_pct, 0.30)

        # RR 约束修复
        if tp_pct / sl_pct < 2.0:
            tp_pct = min(sl_pct * 2.0, 0.30)

        if direction > 0:
            sl_px = entry_px * (1 - sl_pct)
            tp_px = entry_px * (1 + tp_pct)
        else:
            sl_px = entry_px * (1 + sl_pct)
            tp_px = entry_px * (1 - tp_pct)

        # 遍历后续 K 线，检查平仓
        exit_px = None
        for j in range(i + 1, min(i + MAX_HOLD_BARS + 1, n)):
            if direction > 0:
                if lows[j] <= sl_px:
                    exit_px = sl_px
                    break
                if highs[j] >= tp_px:
                    exit_px = tp_px
                    break
            else:
                if highs[j] >= sl_px:
                    exit_px = sl_px
                    break
                if lows[j] <= tp_px:
                    exit_px = tp_px
                    break
        if exit_px is None:
            exit_px = closes[min(i + MAX_HOLD_BARS, n - 1)]

        # 计算收益（含手续费，无杠杆，10% 仓位）
        if direction > 0:
            ret = (exit_px - entry_px) / entry_px
        else:
            ret = (entry_px - exit_px) / entry_px
        ret -= 2 * FEE_PCT  # 开仓+平仓手续费
        position_ret = ret * POSITION_PCT  # 组合层面收益率
        trades.append(position_ret)
        equity *= (1 + position_ret)
        equity_curve.append(equity)

        i += TRADE_INTERVAL

    if not trades:
        return BacktestResult(0, 0, 0, 0, 0, 0, 0,
                              {"sl_floor": sl_floor, "tp_floor": tp_floor, "atr_mult": atr_mult})

    trades_arr = np.array(trades)
    win_rate = float(np.mean(trades_arr > 0))
    wins = trades_arr[trades_arr > 0]
    losses = trades_arr[trades_arr <= 0]
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
    avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.001
    avg_rr = avg_win / avg_loss if avg_loss > 0 else 0

    total_return = equity - 1.0

    # 最大回撤
    equity_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(equity_arr)
    drawdown = (equity_arr - peak) / peak
    max_drawdown = float(np.min(drawdown))

    # Calmar
    calmar = total_return / abs(max_drawdown) if max_drawdown < 0 else 0

    # 夏普（假设每笔交易独立，年化因子 sqrt(252)）
    if len(trades_arr) > 1 and np.std(trades_arr) > 0:
        sharpe = float(np.mean(trades_arr) / np.std(trades_arr) * np.sqrt(252))
    else:
        sharpe = 0

    return BacktestResult(
        total_trades=len(trades),
        win_rate=win_rate,
        avg_rr=avg_rr,
        total_return=total_return,
        max_drawdown=max_drawdown,
        calmar=calmar,
        sharpe=sharpe,
        params={"sl_floor": sl_floor, "tp_floor": tp_floor, "atr_mult": atr_mult},
    )


def optimize_params(
    symbol: str,
    n_iter: int = 30,
    init_points: int = 10,
    regime: str = "chop",
) -> Tuple[Dict[str, float], BacktestResult]:
    """对单个币种优化 SL/TP 参数"""
    df = load_klines(symbol)
    if df is None or len(df) < 200:
        print(f"[WARN] {symbol} 数据不足，跳过")
        return {}, BacktestResult(0, 0, 0, 0, 0, 0, 0, {})

    def objective(sl_floor: float, tp_floor: float, atr_mult: float) -> float:
        # 硬约束：RR≥2:1
        if tp_floor / sl_floor < 2.0:
            return -10.0

        result = run_backtest(df, symbol, sl_floor, tp_floor, atr_mult, regime)

        # 约束惩罚
        score = result.calmar
        if result.win_rate < 0.40:
            score -= 5.0 * (0.40 - result.win_rate)
        if result.max_drawdown < -0.60:
            score -= 10.0 * (abs(result.max_drawdown) - 0.60)
        if result.total_trades < 10:
            score -= 5.0

        return score

    pbounds = {
        "sl_floor": (0.04, 0.10),
        "tp_floor": (0.12, 0.30),
        "atr_mult": (3.0, 6.0),
    }

    optimizer = BayesianOptimization(
        f=objective,
        pbounds=pbounds,
        random_state=42,
        allow_duplicate_points=True,
    )

    optimizer.maximize(init_points=init_points, n_iter=n_iter)

    best = optimizer.max["params"]
    best_result = run_backtest(df, symbol, best["sl_floor"], best["tp_floor"], best["atr_mult"], regime)

    return best, best_result


def optimize_all(n_iter: int = 20) -> Dict[str, Dict]:
    """优化所有有数据的币种"""
    symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "LINK", "DOGE", "PEPE",
               "UNI", "AAVE", "ADA", "AVAX", "NVDA", "AMZN", "AAPL", "XAU"]
    results = {}
    for sym in symbols:
        path = KLINES_DIR / f"{sym}_1H.csv"
        if not path.exists():
            continue
        print(f"\n{'='*60}")
        print(f"优化 {sym}...")
        best_params, best_result = optimize_params(sym, n_iter=n_iter)
        if best_params:
            results[sym] = {
                "params": best_params,
                "metrics": {
                    "win_rate": round(best_result.win_rate, 4),
                    "avg_rr": round(best_result.avg_rr, 4),
                    "total_return": round(best_result.total_return, 4),
                    "max_drawdown": round(best_result.max_drawdown, 4),
                    "calmar": round(best_result.calmar, 4),
                    "sharpe": round(best_result.sharpe, 4),
                    "trades": best_result.total_trades,
                },
            }
            print(f"  sl_floor={best_params['sl_floor']:.4f} "
                  f"tp_floor={best_params['tp_floor']:.4f} "
                  f"atr_mult={best_params['atr_mult']:.2f}")
            print(f"  胜率={best_result.win_rate*100:.1f}% "
                  f"收益={best_result.total_return*100:.1f}% "
                  f"回撤={best_result.max_drawdown*100:.1f}% "
                  f"Calmar={best_result.calmar:.2f}")
    return results


def main():
    parser = argparse.ArgumentParser(description="三维分类 SL/TP 贝叶斯优化")
    parser.add_argument("--symbol", type=str, help="单个币种优化")
    parser.add_argument("--all", action="store_true", help="优化所有币种")
    parser.add_argument("--n-iter", type=int, default=20, help="优化迭代次数")
    parser.add_argument("--regime", type=str, default="chop",
                        choices=["bull", "chop", "bear"], help="市场形态")
    parser.add_argument("--output", type=str, default="sltp_optimized_params.json",
                        help="输出文件")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    if args.all:
        results = optimize_all(n_iter=args.n_iter)
    elif args.symbol:
        best_params, best_result = optimize_params(args.symbol, n_iter=args.n_iter, regime=args.regime)
        results = {args.symbol: {"params": best_params, "metrics": {
            "win_rate": round(best_result.win_rate, 4),
            "total_return": round(best_result.total_return, 4),
            "max_drawdown": round(best_result.max_drawdown, 4),
            "calmar": round(best_result.calmar, 4),
        }}}
    else:
        parser.print_help()
        return

    # 保存结果
    out_path = Path(args.output)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到 {out_path}")


if __name__ == "__main__":
    main()
