#!/usr/bin/env python3
"""
贝叶斯参数优化 — 用Optuna搜索五角校验最优参数。

优化目标：最大化夏普比率（兼顾收益和风险）
搜索空间：8个关键参数（Ising/TDA/力学引擎/P3联动）
评估方式：WalkForwardBacktester 3折回测（BTC+ETH平均）
"""
import sys
import os
import json
import time
import logging
import pandas as pd
import numpy as np

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

import importlib
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ── 当前参数基线（用于回退）──
BASELINE_PARAMS = {
    "ISING_TEMP_SCALE": 500.0,
    "ISING_ORDERED_RATIO": 0.85,
    "ISING_DISORDERED_RATIO": 1.15,
    "ISING_MAGNETIZATION_THRESHOLD": 0.15,
    "ISING_ENERGY_SPIKE_FACTOR": 2.5,
    "TDA_BETTI_SPIKE_FACTOR": 3.0,
    "TDA_BOTTLENECK_DISTANCE_THRESHOLD": 0.5,
    "REVERSAL_WARNING_THRESHOLD": 0.15,
}

# 数据缓存
_DATA_CACHE = {}


def load_klines(symbol, timeframe="1H"):
    if symbol not in _DATA_CACHE:
        data_dir = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
        filepath = os.path.join(data_dir, f"{symbol}_{timeframe}.csv")
        if os.path.exists(filepath):
            df = pd.read_csv(filepath)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df.set_index("timestamp", inplace=True)
            _DATA_CACHE[symbol] = df
        else:
            _DATA_CACHE[symbol] = None
    return _DATA_CACHE[symbol]


def apply_params(trial):
    """将Optuna trial的参数应用到所有消费模块（patch本地引用）"""
    from scripts.memory_l4.bcrm import _constants as const
    from scripts.memory_l4.bcrm import ising_phase_detector as ising_mod
    from scripts.memory_l4.bcrm import force_engine as force_mod
    from scripts.memory_l4.bcrm import tda_early_warning as tda_mod

    params = {
        "ISING_TEMP_SCALE": trial.suggest_float("ISING_TEMP_SCALE", 300.0, 800.0),
        "ISING_ORDERED_RATIO": trial.suggest_float("ISING_ORDERED_RATIO", 0.70, 0.95),
        "ISING_DISORDERED_RATIO": trial.suggest_float("ISING_DISORDERED_RATIO", 1.05, 1.30),
        "ISING_MAGNETIZATION_THRESHOLD": trial.suggest_float("ISING_MAGNETIZATION_THRESHOLD", 0.10, 0.25),
        "ISING_ENERGY_SPIKE_FACTOR": trial.suggest_float("ISING_ENERGY_SPIKE_FACTOR", 1.5, 3.5),
        "TDA_BETTI_SPIKE_FACTOR": trial.suggest_float("TDA_BETTI_SPIKE_FACTOR", 2.0, 4.0),
        "TDA_BOTTLENECK_DISTANCE_THRESHOLD": trial.suggest_float("TDA_BOTTLENECK_DISTANCE_THRESHOLD", 0.3, 0.8),
        "REVERSAL_WARNING_THRESHOLD": trial.suggest_float("REVERSAL_WARNING_THRESHOLD", 0.08, 0.30),
    }

    # Patch _constants
    for k, v in params.items():
        setattr(const, k, v)

    # Patch ising_phase_detector 本地引用
    for k in ["ISING_TEMP_SCALE", "ISING_ORDERED_RATIO", "ISING_DISORDERED_RATIO",
              "ISING_MAGNETIZATION_THRESHOLD", "ISING_ENERGY_SPIKE_FACTOR"]:
        if hasattr(ising_mod, k):
            setattr(ising_mod, k, params[k])

    # Patch force_engine 本地引用
    if hasattr(force_mod, "REVERSAL_WARNING_THRESHOLD"):
        setattr(force_mod, "REVERSAL_WARNING_THRESHOLD", params["REVERSAL_WARNING_THRESHOLD"])

    # Patch tda_early_warning 本地引用
    for k in ["TDA_BETTI_SPIKE_FACTOR", "TDA_BOTTLENECK_DISTANCE_THRESHOLD"]:
        if hasattr(tda_mod, k):
            setattr(tda_mod, k, params[k])

    return params


def run_backtest(symbol, df):
    """运行单币种回测，返回关键指标"""
    # 每次重建TriangleVerifier以应用新参数
    from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester
    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=3,
        conf_threshold=0.40,
        tp_atr=3.0,
        sl_atr=2.0,
        max_hold_bars=60,
    )
    # 重建triangle_verifier以加载新参数
    if bt.enable_pentagon:
        from scripts.memory_l4.triangle_verifier import TriangleVerifier
        bt._triangle_verifier = TriangleVerifier()

    result = bt.run(df, verbose=False)
    return result


def objective(trial):
    """Optuna目标函数：最大化平均夏普比率"""
    params = apply_params(trial)

    symbols = ["BTC", "ETH"]
    sharpes = []
    returns = []
    drawdowns = []
    t0 = time.time()

    for symbol in symbols:
        df = load_klines(symbol)
        if df is None or len(df) < 800:
            continue

        try:
            result = run_backtest(symbol, df)
            sharpes.append(result.sharpe_ratio)
            returns.append(result.total_return)
            drawdowns.append(result.max_drawdown)
        except Exception as e:
            logger.warning(f"[{symbol}] 回测失败: {e}")
            return -10.0  # 惩罚失败

    if not sharpes:
        return -10.0

    avg_sharpe = np.mean(sharpes)
    avg_return = np.mean(returns)
    avg_dd = np.mean(drawdowns)

    # 综合目标：夏普为主，收益为辅，回撤惩罚
    # score = sharpe + 0.01 * return - 0.05 * drawdown
    score = avg_sharpe + 0.01 * avg_return - 0.05 * avg_dd

    trial.set_user_attr("avg_sharpe", avg_sharpe)
    trial.set_user_attr("avg_return", avg_return)
    trial.set_user_attr("avg_drawdown", avg_dd)
    trial.set_user_attr("sharpes", sharpes)
    trial.set_user_attr("returns", returns)

    elapsed = time.time() - t0
    print(f"    Trial #{trial.number}: 得分={score:.4f}, 夏普={avg_sharpe:.2f}, "
          f"收益={avg_return:.1f}%, 回撤={avg_dd:.1f}% ({elapsed:.0f}秒)", flush=True)

    return score


def main():
    print("=" * 80)
    print("  贝叶斯参数优化 — 五角校验参数搜索")
    print("=" * 80)
    print(f"\n  优化目标：夏普比率 + 收益 - 回撤惩罚")
    print(f"  搜索空间：8个参数")
    print(f"  评估方式：BTC+ETH 3折Walk-Forward回测")
    print(f"  试验次数：30次")
    print(f"\n  当前基线参数：")
    for k, v in BASELINE_PARAMS.items():
        print(f"    {k} = {v}")

    # 先运行基线
    print(f"\n  [基线] 运行当前参数回测...")
    from scripts.memory_l4.bcrm import _constants as const
    from scripts.memory_l4.bcrm import ising_phase_detector as ising_mod
    from scripts.memory_l4.bcrm import force_engine as force_mod
    from scripts.memory_l4.bcrm import tda_early_warning as tda_mod
    # 确保使用基线参数（patch所有模块）
    for k, v in BASELINE_PARAMS.items():
        setattr(const, k, v)
        if hasattr(ising_mod, k):
            setattr(ising_mod, k, v)
        if hasattr(force_mod, k):
            setattr(force_mod, k, v)
        if hasattr(tda_mod, k):
            setattr(tda_mod, k, v)

    baseline_scores = {}
    for symbol in ["BTC", "ETH"]:
        df = load_klines(symbol)
        if df is None:
            continue
        result = run_backtest(symbol, df)
        baseline_scores[symbol] = {
            "sharpe": result.sharpe_ratio,
            "return": result.total_return,
            "drawdown": result.max_drawdown,
            "trades": result.total_trades,
            "win_rate": result.overall_win_rate,
            "profit_factor": result.profit_factor,
        }
        print(f"    {symbol}: 夏普={result.sharpe_ratio:.2f}, 收益={result.total_return:.2f}%, 回撤={result.max_drawdown:.2f}%")

    baseline_sharpe = np.mean([s["sharpe"] for s in baseline_scores.values()])
    baseline_return = np.mean([s["return"] for s in baseline_scores.values()])
    baseline_dd = np.mean([s["drawdown"] for s in baseline_scores.values()])
    baseline_score = baseline_sharpe + 0.01 * baseline_return - 0.05 * baseline_dd
    print(f"    基线综合得分: {baseline_score:.4f}")

    # 运行贝叶斯优化
    print(f"\n  [优化] 开始贝叶斯搜索（30 trials）...")
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    t0 = time.time()
    study.optimize(objective, n_trials=30, show_progress_bar=False)
    elapsed = time.time() - t0

    best = study.best_trial
    print(f"\n  优化完成！耗时: {elapsed:.0f}秒")
    print(f"\n  最优试验 #{best.number}:")
    print(f"    综合得分: {best.value:.4f} (基线: {baseline_score:.4f})")
    print(f"    平均夏普: {best.user_attrs.get('avg_sharpe', 0):.4f} (基线: {baseline_sharpe:.4f})")
    print(f"    平均收益: {best.user_attrs.get('avg_return', 0):.4f}% (基线: {baseline_return:.4f}%)")
    print(f"    平均回撤: {best.user_attrs.get('avg_drawdown', 0):.4f}% (基线: {baseline_dd:.4f}%)")
    print(f"\n  最优参数：")
    for k, v in best.params.items():
        old = BASELINE_PARAMS.get(k, "?")
        print(f"    {k}: {v:.4f} (基线: {old})")

    # 判断是否采纳
    improvement = best.value - baseline_score
    print(f"\n  得分提升: {improvement:+.4f}")

    if improvement > 0.1:
        print(f"\n  结论: ✅ 优化有效，建议采纳新参数")
        # 保存最优参数
        output_path = os.path.join(SCRIPT_DIR, "optimal_params.json")
        with open(output_path, "w") as f:
            json.dump({
                "params": best.params,
                "score": best.value,
                "baseline_score": baseline_score,
                "improvement": improvement,
                "user_attrs": best.user_attrs,
            }, f, indent=2)
        print(f"  参数已保存: {output_path}")
    else:
        print(f"\n  结论: ❌ 优化未显著提升（提升<0.1），回退到基线参数")
        # 恢复基线参数（patch所有模块）
        for k, v in BASELINE_PARAMS.items():
            setattr(const, k, v)
            if hasattr(ising_mod, k):
                setattr(ising_mod, k, v)
            if hasattr(force_mod, k):
                setattr(force_mod, k, v)
            if hasattr(tda_mod, k):
                setattr(tda_mod, k, v)
        print(f"  已回退到基线参数")

    # 打印Top 5试验
    print(f"\n  Top 5试验：")
    sorted_trials = sorted(
        [t for t in study.trials if t.value is not None],
        key=lambda t: t.value,
        reverse=True
    )[:5]
    for t in sorted_trials:
        print(f"    #{t.number}: 得分={t.value:.4f}, 夏普={t.user_attrs.get('avg_sharpe', 0):.2f}, "
              f"收益={t.user_attrs.get('avg_return', 0):.2f}%, 回撤={t.user_attrs.get('avg_drawdown', 0):.2f}%")


if __name__ == "__main__":
    main()
