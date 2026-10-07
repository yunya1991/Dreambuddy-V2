#!/usr/bin/env python3
"""消融实验：验证三维分类各维度的有效性

5 组配置：
  1. full_3d      : 完整三维分类（asset_class × market_cap × regime）
  2. no_regime    : 去掉市场形态维度（regime 固定 chop）
  3. no_mcap      : 去掉市值等级维度（market_cap 固定 large）
  4. no_asset     : 去掉资产类别维度（asset_class 固定 crypto_large）
  5. baseline     : 无分类，统一参数（SL=8%, TP=24%, ATR=4.5）

对比指标：胜率、总收益、最大回撤、Calmar、夏普
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

_THIS_DIR = Path(__file__).resolve().parent
_MEMORY_L4 = _THIS_DIR.parent
_SCRIPTS = _MEMORY_L4.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from memory_l4.bcrm2.asset_classifier import classify_asset
from memory_l4.bcrm2.sl_tp_config import get_sltp_params
from memory_l4.bcrm2.sltp_bayesian_optimizer import (
    load_klines, compute_atr, FEE_PCT, POSITION_PCT,
    TRADE_INTERVAL, MAX_HOLD_BARS,
)

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "LINK", "DOGE", "PEPE",
           "UNI", "AAVE", "NVDA", "AMZN"]


def detect_regime(closes: np.ndarray, i: int, lookback: int = 50) -> str:
    """简单市场形态检测：基于 MA 斜率

    - bull: MA20 斜率 > 0.5%（上升趋势）
    - bear: MA20 斜率 < -0.5%（下降趋势）
    - chop: 其他（震荡）
    """
    if i < lookback + 20:
        return "chop"
    ma = pd.Series(closes[:i+1]).rolling(20).mean().values
    ma_recent = ma[i]
    ma_past = ma[i - lookback]
    if ma_past <= 0 or np.isnan(ma_recent) or np.isnan(ma_past):
        return "chop"
    slope = (ma_recent - ma_past) / ma_past
    if slope > 0.005:
        return "bull"
    elif slope < -0.005:
        return "bear"
    else:
        return "chop"


def run_ablation_backtest(
    df: pd.DataFrame,
    symbol: str,
    config_name: str,
) -> Dict[str, float]:
    """运行单组消融配置的回测"""
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    n = len(closes)

    atr_pct = compute_atr(closes, highs, lows, period=14)
    ma200 = pd.Series(closes).rolling(200).mean().values

    trades: List[float] = []
    equity = 1.0
    equity_curve = [1.0]

    # 获取资产分类
    asset_class, mcap_tier = classify_asset(symbol)

    i = 250
    while i < n - 1:
        if np.isnan(ma200[i]):
            i += TRADE_INTERVAL
            continue
        direction = 1 if closes[i] > ma200[i] else -1
        entry_px = closes[i]
        atr = atr_pct[i] if atr_pct[i] > 0 else 0.01

        # 检测市场形态（仅 full_3d 使用）
        regime = detect_regime(closes, i) if config_name == "full_3d" else "chop"

        # 根据配置获取参数
        if config_name == "baseline":
            sl_floor, tp_floor, atr_mult = 0.08, 0.24, 4.5
        else:
            # 决定各维度
            ac = asset_class if config_name != "no_asset" else "crypto_large"
            mc = mcap_tier if config_name != "no_mcap" else "large"
            # regime 维度：full_3d 用检测值，其他用 chop
            r = regime if config_name == "full_3d" else "chop"

            params = get_sltp_params(ac, mc, r)
            sl_floor = params.sl_floor
            tp_floor = params.tp_floor
            atr_mult = (params.atr_mult_range[0] + params.atr_mult_range[1]) / 2

        sl_pct = max(atr_mult * atr, sl_floor)
        sl_pct = min(sl_pct, 0.15)
        tp_pct = max(sl_pct * 3.0, tp_floor)
        tp_pct = min(tp_pct, 0.30)
        if tp_pct / sl_pct < 2.0:
            tp_pct = min(sl_pct * 2.0, 0.30)

        if direction > 0:
            sl_px, tp_px = entry_px * (1 - sl_pct), entry_px * (1 + tp_pct)
        else:
            sl_px, tp_px = entry_px * (1 + sl_pct), entry_px * (1 - tp_pct)

        exit_px = None
        for j in range(i + 1, min(i + MAX_HOLD_BARS + 1, n)):
            if direction > 0:
                if lows[j] <= sl_px: exit_px = sl_px; break
                if highs[j] >= tp_px: exit_px = tp_px; break
            else:
                if highs[j] >= sl_px: exit_px = sl_px; break
                if lows[j] <= tp_px: exit_px = tp_px; break
        if exit_px is None:
            exit_px = closes[min(i + MAX_HOLD_BARS, n - 1)]

        if direction > 0:
            ret = (exit_px - entry_px) / entry_px
        else:
            ret = (entry_px - exit_px) / entry_px
        ret -= 2 * FEE_PCT
        position_ret = ret * POSITION_PCT
        trades.append(position_ret)
        equity *= (1 + position_ret)
        equity_curve.append(equity)
        i += TRADE_INTERVAL

    if not trades:
        return {"trades": 0, "win_rate": 0, "total_return": 0,
                "max_drawdown": 0, "calmar": 0, "sharpe": 0}

    trades_arr = np.array(trades)
    win_rate = float(np.mean(trades_arr > 0))
    total_return = equity - 1.0
    equity_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(equity_arr)
    drawdown = (equity_arr - peak) / peak
    max_drawdown = float(np.min(drawdown))
    calmar = total_return / abs(max_drawdown) if max_drawdown < 0 else 0
    sharpe = float(np.mean(trades_arr) / np.std(trades_arr) * np.sqrt(252)) if np.std(trades_arr) > 0 else 0

    return {
        "trades": len(trades),
        "win_rate": round(win_rate, 4),
        "total_return": round(total_return, 4),
        "max_drawdown": round(max_drawdown, 4),
        "calmar": round(calmar, 4),
        "sharpe": round(sharpe, 4),
    }


def main():
    configs = ["full_3d", "no_regime", "no_mcap", "no_asset", "baseline"]
    results: Dict[str, Dict[str, Dict]] = {}

    for config in configs:
        print(f"\n{'='*60}")
        print(f"配置: {config}")
        results[config] = {}
        for sym in SYMBOLS:
            df = load_klines(sym)
            if df is None or len(df) < 300:
                continue
            res = run_ablation_backtest(df, sym, config)
            results[config][sym] = res
            print(f"  {sym:6s} WR={res['win_rate']*100:5.1f}% "
                  f"ret={res['total_return']*100:+6.1f}% "
                  f"DD={res['max_drawdown']*100:6.1f}% "
                  f"Calmar={res['calmar']:+5.2f}")

    # 汇总：各配置的平均指标
    print(f"\n{'='*60}")
    print("消融实验汇总（所有币种平均）")
    print(f"{'配置':<12} {'胜率':>8} {'收益':>8} {'回撤':>8} {'Calmar':>8} {'Sharpe':>8}")
    print("-" * 56)
    summary = {}
    for config in configs:
        sym_results = list(results[config].values())
        if not sym_results:
            continue
        avg_wr = np.mean([r["win_rate"] for r in sym_results])
        avg_ret = np.mean([r["total_return"] for r in sym_results])
        avg_dd = np.mean([r["max_drawdown"] for r in sym_results])
        avg_calmar = np.mean([r["calmar"] for r in sym_results])
        avg_sharpe = np.mean([r["sharpe"] for r in sym_results])
        summary[config] = {
            "avg_win_rate": round(float(avg_wr), 4),
            "avg_total_return": round(float(avg_ret), 4),
            "avg_max_drawdown": round(float(avg_dd), 4),
            "avg_calmar": round(float(avg_calmar), 4),
            "avg_sharpe": round(float(avg_sharpe), 4),
            "n_symbols": len(sym_results),
        }
        print(f"{config:<12} {avg_wr*100:7.1f}% {avg_ret*100:+7.1f}% "
              f"{avg_dd*100:7.1f}% {avg_calmar:+7.2f} {avg_sharpe:+7.2f}")

    # 保存
    out = {"configs": results, "summary": summary}
    out_path = Path(__file__).parent / "ablation_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到 {out_path}")

    # 相对 Baseline 的提升
    print(f"\n{'='*60}")
    print("相对 Baseline 的提升")
    base = summary.get("baseline", {})
    for config in configs:
        if config == "baseline":
            continue
        s = summary.get(config, {})
        if base and s:
            calmar_gain = (s["avg_calmar"] - base["avg_calmar"]) / abs(base["avg_calmar"]) * 100 if base["avg_calmar"] != 0 else 0
            ret_gain = (s["avg_total_return"] - base["avg_total_return"]) * 100
            print(f"  {config:<12} Calmar {calmar_gain:+.1f}% | 收益 {ret_gain:+.1f}%")


if __name__ == "__main__":
    main()
