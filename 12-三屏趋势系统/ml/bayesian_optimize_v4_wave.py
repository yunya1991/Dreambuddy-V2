#!/usr/bin/env python3
"""V4+波浪互斥融合 - 贝叶斯参数优化

使用 Optuna TPE 采样器优化 EWaveStrategyAdapter 的关键参数：
- 波浪加仓权重 wave_weight
- 波浪置信度阈值 confirm_threshold
- 抄底仓位上限 bottom_position_cap
- 波浪基础仓位 base_position
- 波浪最大仓位上限 max_position
- ZigZag 转折阈值 zigzag_threshold

优化目标：最大化 Calmar 比率（年化收益/最大回撤）
约束条件：年化收益 ≥ 纯V4基线（valid_start=730）

策略线归属：[MAIN] 主线代码
"""
import os
import sys
import json
import time
import argparse
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


def load_data(symbol="BTC"):
    path = os.path.join(BASE_DIR, f"data/historical/{symbol}_1D_730d.json")
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )
    return prices


def compute_v4_position(prices, symbol="BTC"):
    from ml.halving_top_exit_strategy import HalvingTopExitStrategy
    strategy = HalvingTopExitStrategy(
        symbol=symbol,
        is_btc=(symbol == "BTC"),
        btc_prices=prices if symbol == "BTC" else None,
    )
    position_series = strategy.generate_signals(prices)
    position_arr = position_series.values if hasattr(position_series, 'values') else np.array(position_series)
    return np.abs(position_arr), np.sign(position_arr)


def generate_wave_signals(prices, zigzag_threshold=0.05):
    from ml.ewave_recognizer import ElliottWaveRecognizer
    recognizer = ElliottWaveRecognizer(zigzag_threshold=zigzag_threshold)
    n = len(prices)
    signals = []
    confs = []
    min_window = 90
    for i in range(n):
        if i < min_window:
            signals.append("WAIT")
            confs.append(0.0)
            continue
        slice_df = prices.iloc[: i + 1]
        try:
            ws = recognizer.identify_waves(slice_df)
            signals.append(ws.signal)
            confs.append(ws.confidence)
        except Exception:
            signals.append("WAIT")
            confs.append(0.0)
    return np.array(signals), np.array(confs)


def compute_v4_wave_mutex_fusion(
    v4_pos, v4_dir, wave_signals, wave_confs,
    wave_weight=0.3, confirm_threshold=0.6, bottom_position_cap=0.3,
):
    """V4+波浪互斥融合（与 comprehensive_strategy_comparison.py 一致）"""
    n = len(v4_pos)
    fusion_pos = np.zeros(n)
    fusion_dir = np.zeros(n)

    wave_long = ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
    wave_short = ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")

    for i in range(n):
        v4_p = v4_pos[i] * v4_dir[i]
        v4_d = v4_dir[i]
        sig = wave_signals[i]
        wave_conf = float(wave_confs[i])
        is_wave_long = sig in wave_long
        is_wave_short = sig in wave_short

        if v4_d > 0:
            if is_wave_long and wave_conf >= confirm_threshold:
                add_amount = wave_weight * wave_conf
                total = v4_p + add_amount
                total = min(total, 1.0)
                fusion_pos[i] = abs(total)
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = 1
        elif v4_d == 0:
            if is_wave_long and wave_conf >= confirm_threshold:
                bottom_pos = wave_weight * wave_conf
                bottom_pos = min(bottom_pos, bottom_position_cap)
                fusion_pos[i] = bottom_pos
                fusion_dir[i] = 1
            else:
                fusion_pos[i] = 0.0
                fusion_dir[i] = 0
        else:
            if is_wave_long and wave_conf >= confirm_threshold:
                fusion_pos[i] = abs(v4_p) * 0.5
                fusion_dir[i] = -1
            else:
                fusion_pos[i] = abs(v4_p)
                fusion_dir[i] = -1

    return fusion_pos, fusion_dir


def backtest_position(position, direction, prices, cost_pct=0.001, valid_start=730):
    n = len(prices)
    closes = prices["close"].values
    daily_ret = np.zeros(n)
    daily_ret[1:] = closes[1:] / closes[:-1] - 1

    strategy_ret = position * direction * daily_ret
    pos_with_dir = position * direction
    position_change = np.abs(np.diff(np.concatenate([[0], pos_with_dir])))
    cost = position_change * cost_pct
    strategy_ret_net = strategy_ret - cost

    eff_n = n - valid_start
    if eff_n <= 0:
        return None
    years = eff_n / 365
    cum_ret_arr = np.cumprod(1 + strategy_ret_net) - 1
    total_return_valid = cum_ret_arr[-1] - cum_ret_arr[valid_start] if valid_start > 0 else cum_ret_arr[-1]
    ann_ret = (1 + total_return_valid) ** (1 / years) - 1 if years > 0 and total_return_valid > -1 else -1.0

    eff_ret = strategy_ret_net[valid_start:]
    daily_nonzero = eff_ret[eff_ret != 0]
    if len(daily_nonzero) > 10:
        sharpe = np.mean(daily_nonzero) / (np.std(daily_nonzero) + 1e-10) * np.sqrt(365)
    else:
        sharpe = 0.0

    cum_value = np.cumprod(1 + eff_ret)
    running_max = np.maximum.accumulate(cum_value)
    drawdown = (cum_value - running_max) / running_max
    max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0
    avg_pos = float(np.mean(position[valid_start:]))

    return {
        "ann_return": float(ann_ret),
        "total_return": float(total_return_valid),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "avg_position": avg_pos,
    }


def objective(trial, prices, v4_pos, v4_dir, wave_signals_cache, wave_confs_cache, baseline_metrics):
    """Optuna 目标函数：最大化 Calmar 比率"""
    wave_weight = trial.suggest_float("wave_weight", 0.1, 0.6, step=0.05)
    confirm_threshold = trial.suggest_float("confirm_threshold", 0.4, 0.8, step=0.05)
    bottom_position_cap = trial.suggest_float("bottom_position_cap", 0.1, 0.5, step=0.05)
    zigzag_idx = trial.suggest_categorical("zigzag_threshold_idx", [0, 1, 2])
    zigzag_thresholds = [0.03, 0.05, 0.08]
    zigzag_threshold = zigzag_thresholds[zigzag_idx]

    zigzag_key = f"zz_{zigzag_threshold}"
    if zigzag_key in wave_signals_cache:
        wave_signals = wave_signals_cache[zigzag_key]
        wave_confs = wave_confs_cache[zigzag_key]
    else:
        wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=zigzag_threshold)
        wave_signals_cache[zigzag_key] = wave_signals
        wave_confs_cache[zigzag_key] = wave_confs

    fusion_pos, fusion_dir = compute_v4_wave_mutex_fusion(
        v4_pos, v4_dir, wave_signals, wave_confs,
        wave_weight=wave_weight,
        confirm_threshold=confirm_threshold,
        bottom_position_cap=bottom_position_cap,
    )

    metrics = backtest_position(fusion_pos, fusion_dir, prices, valid_start=730)
    if metrics is None:
        return -10.0

    if metrics["ann_return"] < baseline_metrics["ann_return"] - 0.01:
        return -10.0

    return metrics["calmar"]


def run_optimization(symbol="BTC", n_trials=50, output_path=None):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    print(f"\n{'='*80}")
    print(f"  V4+波浪互斥融合 - 贝叶斯参数优化 ({symbol})")
    print(f"{'='*80}")

    prices = load_data(symbol)
    n = len(prices)
    print(f"\n数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    print("\n[1/3] 计算 V4 基线...")
    t0 = time.time()
    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    print(f"  耗时: {time.time()-t0:.1f}s, 平均仓位: {np.mean(v4_pos):.3f}")

    baseline_metrics = backtest_position(v4_pos, v4_dir, prices, valid_start=730)
    print(f"\n纯V4基线 (valid_start=730):")
    print(f"  年化: {baseline_metrics['ann_return']*100:.2f}%")
    print(f"  夏普: {baseline_metrics['sharpe']:.3f}")
    print(f"  回撤: {baseline_metrics['max_drawdown']*100:.2f}%")
    print(f"  Calmar: {baseline_metrics['calmar']:.3f}")

    print("\n[2/3] 预计算波浪信号（3个zigzag阈值）...")
    wave_signals_cache = {}
    wave_confs_cache = {}
    for zz in [0.03, 0.05, 0.08]:
        t0 = time.time()
        sigs, confs = generate_wave_signals(prices, zigzag_threshold=zz)
        wave_signals_cache[f"zz_{zz}"] = sigs
        wave_confs_cache[f"zz_{zz}"] = confs
        print(f"  zigzag={zz}: {time.time()-t0:.1f}s")

    default_params = {
        "wave_weight": 0.3,
        "confirm_threshold": 0.6,
        "bottom_position_cap": 0.3,
        "zigzag_threshold_idx": 1,
    }
    default_fusion_pos, default_fusion_dir = compute_v4_wave_mutex_fusion(
        v4_pos, v4_dir,
        wave_signals_cache["zz_0.05"], wave_confs_cache["zz_0.05"],
        **{k: v for k, v in default_params.items() if k != "zigzag_threshold_idx"},
    )
    default_metrics = backtest_position(default_fusion_pos, default_fusion_dir, prices, valid_start=730)
    print(f"\n默认参数融合基线:")
    print(f"  年化: {default_metrics['ann_return']*100:.2f}%")
    print(f"  夏普: {default_metrics['sharpe']:.3f}")
    print(f"  回撤: {default_metrics['max_drawdown']*100:.2f}%")
    print(f"  Calmar: {default_metrics['calmar']:.3f}")

    print(f"\n[3/3] 贝叶斯优化（{n_trials} trials，目标: 最大化 Calmar）...")
    wave_signals_cache_opt = wave_signals_cache.copy()
    wave_confs_cache_opt = wave_confs_cache.copy()

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    t0 = time.time()
    study.optimize(
        lambda trial: objective(
            trial, prices, v4_pos, v4_dir,
            wave_signals_cache_opt, wave_confs_cache_opt, baseline_metrics,
        ),
        n_trials=n_trials,
        show_progress_bar=False,
    )
    print(f"  优化耗时: {time.time()-t0:.1f}s")

    best = study.best_params
    zigzag_thresholds = [0.03, 0.05, 0.08]
    best["zigzag_threshold"] = zigzag_thresholds[best.pop("zigzag_threshold_idx")]

    print(f"\n{'='*80}")
    print(f"  优化结果")
    print(f"{'='*80}")
    print(f"\n最佳参数:")
    for k, v in best.items():
        print(f"  {k}: {v}")

    best_fusion_pos, best_fusion_dir = compute_v4_wave_mutex_fusion(
        v4_pos, v4_dir,
        wave_signals_cache[f"zz_{best['zigzag_threshold']}"],
        wave_confs_cache[f"zz_{best['zigzag_threshold']}"],
        wave_weight=best["wave_weight"],
        confirm_threshold=best["confirm_threshold"],
        bottom_position_cap=best["bottom_position_cap"],
    )
    best_metrics = backtest_position(best_fusion_pos, best_fusion_dir, prices, valid_start=730)

    print(f"\n最佳参数回测:")
    print(f"  年化: {best_metrics['ann_return']*100:.2f}%")
    print(f"  夏普: {best_metrics['sharpe']:.3f}")
    print(f"  回撤: {best_metrics['max_drawdown']*100:.2f}%")
    print(f"  Calmar: {best_metrics['calmar']:.3f}")

    print(f"\n{'='*80}")
    print(f"  对比总结")
    print(f"{'='*80}")
    print(f"\n{'指标':<12} {'纯V4':>10} {'默认融合':>10} {'优化融合':>10} {'优化-默认':>10}")
    print(f"{'-'*52}")
    for key, label in [("ann_return", "年化"), ("sharpe", "夏普"), ("max_drawdown", "回撤"), ("calmar", "Calmar")]:
        v4_v = baseline_metrics[key]
        def_v = default_metrics[key]
        opt_v = best_metrics[key]
        diff = opt_v - def_v
        if key == "max_drawdown":
            print(f"{label:<12} {v4_v*100:>9.2f}% {def_v*100:>9.2f}% {opt_v*100:>9.2f}% {diff*100:>+9.2f}%")
        else:
            print(f"{label:<12} {v4_v:>10.4f} {def_v:>10.4f} {opt_v:>10.4f} {diff:>+10.4f}")

    is_better = (
        best_metrics["ann_return"] > default_metrics["ann_return"]
        and best_metrics["calmar"] > default_metrics["calmar"]
    )
    if is_better:
        print(f"\n✅ 优化参数优于默认参数")
    else:
        print(f"\n❌ 优化参数未明显优于默认参数，建议回退")

    if output_path is None:
        output_path = os.path.join(
            BASE_DIR,
            f"ml/backtest_results/bayesian_optimization_{symbol}.json",
        )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result = {
        "symbol": symbol,
        "baseline_v4": baseline_metrics,
        "default_fusion": default_metrics,
        "optimized_fusion": best_metrics,
        "best_params": best,
        "default_params": {
            "wave_weight": 0.3,
            "confirm_threshold": 0.6,
            "bottom_position_cap": 0.3,
            "zigzag_threshold": 0.05,
        },
        "is_better": is_better,
        "n_trials": n_trials,
        "data_start": str(prices.index[0].date()),
        "data_end": str(prices.index[-1].date()),
        "valid_start": 730,
        "total_days": n,
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n结果已保存: {output_path}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC", type=str)
    parser.add_argument("--trials", default=50, type=int)
    args = parser.parse_args()

    run_optimization(symbol=args.symbol, n_trials=args.trials)
