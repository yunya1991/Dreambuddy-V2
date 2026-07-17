"""分市场状态参数优化（快速版）

优化策略：预计算最小阻力信号一次，然后快速测试不同参数组合
市场状态划分：牛市/熊市/震荡
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import json
from itertools import product
from datetime import datetime

from data.market_data import fetch_historical_candles
from backtest.engine import BacktestEngine


def fetch_real_data(inst_id, days=730):
    candles = fetch_historical_candles(inst_id, bar="1D", days=days)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def resample_to_weekly(daily_df):
    df = daily_df.copy()
    df.index = pd.to_datetime(df.index)
    weekly = df.resample("W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    return weekly


def classify_market_regime(prices, ma_long=200, ma_short=50):
    """划分市场状态（放宽标准）"""
    close = prices["close"]
    n = len(close)

    ma200 = close.rolling(window=ma_long, min_periods=ma_long).mean()
    ma50 = close.rolling(window=ma_short, min_periods=ma_short).mean()
    ma200_slope = ma200.pct_change(periods=20)

    # 趋势强度：20天价格变化占ATR的比例
    atr = (prices["high"] - prices["low"]).rolling(window=14).mean()
    directional = close.diff(periods=20).abs()
    trend_strength = directional / (atr * 20 + 1e-8)

    regime = pd.Series("sideways", index=prices.index)

    # 放宽条件：只要价格在MA200上方+MA50在MA200上方就算牛市
    bull_mask = (close > ma200) & (ma50 > ma200) & (ma200_slope > 0)
    bear_mask = (close < ma200) & (ma50 < ma200) & (ma200_slope < 0)

    regime[bull_mask] = "bull"
    regime[bear_mask] = "bear"
    regime.iloc[:ma_long] = "sideways"

    return regime


def precompute_lr_signals(prices, warmup=80, step=1):
    """预计算所有bar的最小阻力信号（只算一次）"""
    from core.least_resistance import compute_least_resistance_3d

    n = len(prices)
    warmup = min(warmup, n - 10)

    history_3d = []
    daily_history_diffs = []

    signals = []
    for i in range(warmup, n):
        if (i - warmup) % step == 0 or i == warmup:
            daily_slice = prices.iloc[:i + 1].copy()
            weekly_df = resample_to_weekly(daily_slice)

            if len(weekly_df) >= 10:
                try:
                    result = compute_least_resistance_3d(
                        weekly_df, daily_slice,
                        daily_history_diffs=daily_history_diffs if daily_history_diffs else None,
                        history_3d=history_3d if history_3d else None,
                    )
                    daily_diff = result.get("daily_diff", 0.0)
                    daily_history_diffs.append(daily_diff)
                    if len(daily_history_diffs) > 30:
                        daily_history_diffs = daily_history_diffs[-30:]

                    history_3d.append({
                        "direction": result["direction"],
                        "velocity": result["velocity"],
                        "acceleration": result["acceleration"],
                    })
                    if len(history_3d) > 20:
                        history_3d = history_3d[-20:]

                    signals.append({
                        "idx": i,
                        "direction": result["direction"],
                        "confidence": result["confidence"],
                        "entry_signal": result["entry_signal"],
                    })
                except Exception:
                    signals.append({
                        "idx": i,
                        "direction": "NEUTRAL",
                        "confidence": 0.0,
                        "entry_signal": "WAIT",
                    })

    return signals


def fast_generate_positions(signals, n, params, ma200, ma50):
    """根据预计算信号和参数快速生成仓位序列"""
    update_step = params["update_step"]
    min_holding = params["min_holding_bars"]
    confirm_bars = params["signal_confirm_bars"]
    max_position = params["max_position"]
    enable_trend_filter = params.get("enable_trend_filter", True)

    positions = np.zeros(n)
    signal_buffer = []
    holding_count = 0
    last_pos = 0.0

    signal_map = {s["idx"]: s for s in signals}

    for i in range(n):
        if i in signal_map:
            s = signal_map[i]
            direction = s["direction"]
            confidence = s["confidence"]
            entry_signal = s["entry_signal"]

            signal_buffer.append(direction)
            if len(signal_buffer) > confirm_bars:
                signal_buffer = signal_buffer[-confirm_bars:]

            if holding_count > 0:
                holding_count -= 1
            else:
                # 信号确认
                if len(signal_buffer) >= confirm_bars:
                    last_n = signal_buffer[-confirm_bars:]
                    if all(d == "BULL" for d in last_n):
                        confirmed = "BULL"
                    elif all(d == "BEAR" for d in last_n):
                        confirmed = "BEAR"
                    else:
                        confirmed = "NEUTRAL"
                else:
                    confirmed = "NEUTRAL"

                # 信号转仓位
                if confirmed == "NEUTRAL" or entry_signal == "WAIT":
                    raw_pos = 0.0
                elif entry_signal == "MUST_ENTER":
                    raw_pos = min(confidence / 100.0, 1.0) * max_position
                elif entry_signal == "TIMING":
                    if confidence < 25.0:
                        raw_pos = 0.0
                    else:
                        raw_pos = min(confidence / 100.0, 1.0) * max_position * 0.3
                else:
                    raw_pos = 0.0

                if confirmed == "BEAR" and raw_pos != 0:
                    raw_pos = -raw_pos

                # 趋势过滤
                if enable_trend_filter and abs(raw_pos) > 0.01:
                    has_ma = (i < len(ma200) and not np.isnan(ma200[i]) and ma200[i] > 0 and
                              i < len(ma50) and not np.isnan(ma50[i]) and ma50[i] > 0)
                    if has_ma:
                        in_bull = ma50[i] > ma200[i]
                        in_bear = ma50[i] < ma200[i]
                        if raw_pos > 0 and in_bear:
                            raw_pos = 0.0
                        elif raw_pos < 0 and in_bull:
                            raw_pos = 0.0

                if raw_pos != last_pos:
                    last_pos = raw_pos
                    if abs(raw_pos) > 0:
                        holding_count = min_holding

        positions[i] = last_pos

    return positions


def fast_backtest(prices, positions, regime):
    """快速回测"""
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    signals = pd.Series(positions, index=prices.index, name="position")
    result = engine.run(prices["close"], signals)
    m = result["metrics"]
    trades = result["trades"]

    # 按市场状态统计
    regime_stats = {}
    for r_name in ["bull", "bear", "sideways"]:
        mask = regime == r_name
        days = int(mask.sum())
        if days == 0:
            regime_stats[r_name] = {"days": 0, "return_pct": 0, "pct": 0}
            continue

        pos = signals[mask]
        daily_ret = prices["close"].pct_change()[mask]
        strategy_ret = pos.shift(1) * daily_ret
        regime_return = (1 + strategy_ret.fillna(0)).prod() - 1

        regime_stats[r_name] = {
            "days": days,
            "return_pct": float(regime_return * 100),
            "pct": float(days / len(regime) * 100),
        }

    n_trades = len(trades) if not trades.empty else 0
    avg_hold = trades["holding_bars"].mean() if n_trades > 0 else 0

    return {
        "return": m["total_return_pct"],
        "sharpe": m["sharpe_ratio"],
        "drawdown": m["max_drawdown_pct"],
        "trades": n_trades,
        "avg_holding": avg_hold,
        "regime_stats": regime_stats,
    }


def main():
    print("=" * 80)
    print("  分市场状态参数优化（快速版）")
    print("=" * 80)

    print("\n[1] 获取BTC历史数据...")
    prices = fetch_real_data("BTC-USDT", days=730)
    if prices.empty:
        print("  数据获取失败")
        return

    n = len(prices)
    print(f"  数据: {n} 天")

    # 市场状态划分
    print("\n[2] 划分市场状态...")
    regime = classify_market_regime(prices)

    bull_days = (regime == "bull").sum()
    bear_days = (regime == "bear").sum()
    side_days = (regime == "sideways").sum()
    print(f"  牛市: {bull_days} 天 ({bull_days/n*100:.1f}%)")
    print(f"  熊市: {bear_days} 天 ({bear_days/n*100:.1f}%)")
    print(f"  震荡: {side_days} 天 ({side_days/n*100:.1f}%)")

    for r_name in ["bull", "bear", "sideways"]:
        mask = regime == r_name
        if mask.sum() > 0:
            subset = prices["close"][mask]
            bh = (subset.iloc[-1] / subset.iloc[0] - 1) * 100
            print(f"  {r_name} 买入持有: {bh:+.2f}%")

    # 预计算信号（只算一次！）
    print("\n[3] 预计算最小阻力信号...")
    import time
    t0 = time.time()
    signals = precompute_lr_signals(prices, warmup=80, step=1)
    t1 = time.time()
    print(f"  完成: {len(signals)} 个信号, 耗时 {t1-t0:.1f}s")

    # 预计算MA
    ma200 = prices["close"].rolling(window=200, min_periods=200).mean().values
    ma50 = prices["close"].rolling(window=50, min_periods=50).mean().values

    # 参数扫描
    param_grid = {
        "update_step": [1, 3, 5],
        "min_holding_bars": [3, 5, 7, 10, 15, 20],
        "signal_confirm_bars": [1, 2, 3, 4],
        "max_position": [0.4, 0.6, 0.8, 1.0],
        "enable_trend_filter": [True],
    }

    total_combos = 1
    for v in param_grid.values():
        total_combos *= len(v)
    print(f"\n[4] 参数扫描 ({total_combos} 种组合)...")

    results = []
    t0 = time.time()

    for idx, combo in enumerate(product(*param_grid.values())):
        params = dict(zip(param_grid.keys(), combo))

        positions = fast_generate_positions(signals, n, params, ma200, ma50)
        r = fast_backtest(prices, positions, regime)
        r["params"] = params
        results.append(r)

        if (idx + 1) % 50 == 0 or idx == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            eta = (total_combos - idx - 1) / rate
            print(f"  进度: {idx+1}/{total_combos} ({(idx+1)/total_combos*100:.0f}%) "
                  f"速率: {rate:.1f}/s ETA: {eta:.0f}s")

    t1 = time.time()
    print(f"  扫描完成: {total_combos} 组合, 耗时 {t1-t0:.1f}s")

    # 找出各状态最优参数
    print(f"\n[5] 各市场状态最优参数:")
    best = {}

    for r_name in ["bull", "bear", "sideways", "overall"]:
        if r_name == "overall":
            sorted_r = sorted(results, key=lambda x: x["return"], reverse=True)
        else:
            sorted_r = sorted(
                results,
                key=lambda x: x["regime_stats"].get(r_name, {}).get("return_pct", -999),
                reverse=True,
            )
        if sorted_r:
            best[r_name] = sorted_r[0]

    print(f"\n{'状态':>8} {'收益%':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6} {'持仓天':>8} | "
          f"{'step':>5} {'hold':>5} {'confirm':>8} {'pos':>5} {'filter':>6}")
    print("-" * 100)

    for r_name in ["bull", "bear", "sideways", "overall"]:
        if r_name not in best:
            continue
        b = best[r_name]
        p = b["params"]
        r_label = {"bull": "牛市", "bear": "熊市", "sideways": "震荡", "overall": "综合"}.get(r_name, r_name)
        tf = "是" if p.get("enable_trend_filter") else "否"
        print(f"{r_label:>8} {b['return']:>+9.2f}% {b['sharpe']:>8.3f} {b['drawdown']:>7.2f}% "
              f"{b['trades']:>6d} {b['avg_holding']:>7.1f}天 | "
              f"{p['update_step']:>5} {p['min_holding_bars']:>5} {p['signal_confirm_bars']:>8} "
              f"{p['max_position']:>5.1f} {tf:>6}")

    # 各状态Top5
    print(f"\n[6] 各状态Top5参数详情:")
    for r_name in ["bull", "bear", "sideways", "overall"]:
        r_label = {"bull": "牛市", "bear": "熊市", "sideways": "震荡", "overall": "综合"}.get(r_name, r_name)
        if r_name == "overall":
            sorted_r = sorted(results, key=lambda x: x["return"], reverse=True)
        else:
            sorted_r = sorted(
                results,
                key=lambda x: x["regime_stats"].get(r_name, {}).get("return_pct", -999),
                reverse=True,
            )

        print(f"\n  {r_label} Top5:")
        for i, r in enumerate(sorted_r[:5]):
            p = r["params"]
            if r_name == "overall":
                reg_ret = r["return"]
                reg_label = "总收益"
            else:
                rs = r["regime_stats"].get(r_name, {})
                reg_ret = rs.get("return_pct", 0)
                reg_label = f"{r_name}收益"
            print(f"    #{i+1} {reg_label}={reg_ret:+.2f}% | "
                  f"总收益={r['return']:+.2f}% 夏普={r['sharpe']:.3f} 回撤={r['drawdown']:.1f}% "
                  f"交易={r['trades']} 持仓={r['avg_holding']:.0f}天 | "
                  f"step={p['update_step']} hold={p['min_holding_bars']} "
                  f"confirm={p['signal_confirm_bars']} pos={p['max_position']}")

    # 保存结果
    os.makedirs("ml/optimization_results", exist_ok=True)
    output = {
        "timestamp": datetime.now().isoformat(),
        "symbol": "BTC-USDT",
        "n_days": n,
        "regime_distribution": {
            "bull": {"days": int(bull_days), "pct": float(bull_days / n * 100)},
            "bear": {"days": int(bear_days), "pct": float(bear_days / n * 100)},
            "sideways": {"days": int(side_days), "pct": float(side_days / n * 100)},
        },
        "best_params": {},
        "top5_per_regime": {},
    }

    for r_name, b in best.items():
        output["best_params"][r_name] = {
            "params": b["params"],
            "return": b["return"],
            "sharpe": b["sharpe"],
            "drawdown": b["drawdown"],
            "trades": b["trades"],
            "avg_holding": b["avg_holding"],
            "regime_stats": b["regime_stats"],
        }

    result_file = f"ml/optimization_results/regime_param_opt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存: {result_file}")


if __name__ == "__main__":
    main()
