#!/usr/bin/env python3
"""
宏观特征维度子集贝叶斯优化 — 搜索最优维度启用组合。

优化目标：最大化综合得分（夏普 + 收益 - 回撤惩罚）
搜索空间：6 个宏观特征维度的启用/禁用（二值组合，2^6=64 种）
  - macro_enable_sentiment    情绪 (5 特征)
  - macro_enable_funding      资金/衍生品 (5 特征)
  - macro_enable_liquidity    流动性 (4 特征)
  - macro_enable_onchain      链上 (3 特征，仅 BTC)
  - macro_enable_smart_money  聪明钱/社交 (4 特征，仅实盘)
  - macro_enable_valuation    估值 (3 特征)

评估方式：BTC+ETH+SOL 三币种 3 折回测（快速评估）
Hold-out：最后 20% 数据独立验证
基线对比：全维度开启 vs 最优子集
"""
import sys
import os
import json
import time
import logging
import importlib

import numpy as np
import pandas as pd

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, PROJECT_ROOT)

# 避免 inspect.py 冲突
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# 数据缓存
_KLINE_CACHE = {}
_REF_DF_CACHE = None


def load_klines(symbol, timeframe="1H", max_bars=3000):
    if symbol not in _KLINE_CACHE:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        df = get_klines(symbol, timeframe, max_bars=max_bars)
        _KLINE_CACHE[symbol] = df
    return _KLINE_CACHE[symbol]


def get_ref_df():
    global _REF_DF_CACHE
    if _REF_DF_CACHE is None:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        _REF_DF_CACHE = get_klines("BTC", "1H", max_bars=3200)
    return _REF_DF_CACHE


# 6 个维度的搜索空间定义
DIMENSIONS = [
    "sentiment",
    "funding",
    "liquidity",
    "onchain",
    "smart_money",
    "valuation",
]


def build_macro_config(trial: optuna.Trial) -> dict:
    """从 Optuna trial 构建宏观维度开关配置"""
    config = {}
    for dim in DIMENSIONS:
        key = f"macro_enable_{dim}"
        config[key] = trial.suggest_categorical(key, [True, False])
    return config


def run_backtest_with_config(symbol, df, macro_config, n_folds=3):
    """用指定宏观维度开关运行回测"""
    from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester

    ref_df = get_ref_df()

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=n_folds,
        conf_threshold=0.40,
        tp_atr=3.0,
        sl_atr=2.0,
        max_hold_bars=60,
        fee_rate=0.0005,
        slippage_rate=0.001,
        feature_selection=True,
        macro_config=macro_config,
    )

    result = bt.run(df, ref_df=ref_df, verbose=False)
    return result


def compute_sharpe_from_trades(trades):
    """从交易列表计算日收益夏普"""
    if not trades:
        return 0.0
    daily_returns = {}
    for t in trades:
        day = t.exit_bar // 24
        daily_returns[day] = daily_returns.get(day, 0.0) + t.pnl_pct
    daily_pnls = list(daily_returns.values())
    if len(daily_pnls) <= 1 or np.std(daily_pnls) == 0:
        return 0.0
    return np.mean(daily_pnls) / np.std(daily_pnls) * np.sqrt(252)


def objective(trial: optuna.Trial) -> float:
    """Optuna 目标函数：最大化综合得分"""
    macro_config = build_macro_config(trial)

    symbols = ["BTC", "ETH", "SOL"]
    all_sharpes = []
    all_returns = []
    all_drawdowns = []
    all_win_rates = []
    t0 = time.time()

    for symbol in symbols:
        df = load_klines(symbol)
        if df is None or len(df) < 800:
            continue

        try:
            result = run_backtest_with_config(symbol, df, macro_config)

            sharpe = compute_sharpe_from_trades(result.all_trades)
            n_trades = len(result.all_trades)
            if n_trades == 0:
                all_sharpes.append(0.0)
                all_returns.append(0.0)
                all_drawdowns.append(0.0)
                all_win_rates.append(0.0)
                continue

            win_rate = sum(1 for t in result.all_trades if t.pnl_pct > 0) / n_trades
            total_ret = sum(t.pnl_pct for t in result.all_trades)
            max_loss = min((t.pnl_pct for t in result.all_trades), default=0)
            max_dd = abs(max_loss) if max_loss < 0 else 0

            all_sharpes.append(sharpe)
            all_returns.append(total_ret)
            all_drawdowns.append(max_dd)
            all_win_rates.append(win_rate)

        except Exception as e:
            logger.warning(f"[{symbol}] 回测失败: {e}")
            return -10.0

    if not all_sharpes:
        return -10.0

    avg_sharpe = np.mean(all_sharpes)
    avg_return = np.mean(all_returns)
    avg_dd = np.mean(all_drawdowns)
    avg_wr = np.mean(all_win_rates)

    # 综合目标：夏普为主，收益为辅，回撤惩罚
    score = avg_sharpe + 0.001 * avg_return - 0.02 * avg_dd

    trial.set_user_attr("avg_sharpe", float(avg_sharpe))
    trial.set_user_attr("avg_return", float(avg_return))
    trial.set_user_attr("avg_drawdown", float(avg_dd))
    trial.set_user_attr("avg_win_rate", float(avg_wr))

    # 记录启用的维度
    enabled_dims = [d for d in DIMENSIONS if macro_config[f"macro_enable_{d}"]]
    trial.set_user_attr("enabled_dims", enabled_dims)
    trial.set_user_attr("n_enabled", len(enabled_dims))

    elapsed = time.time() - t0
    print(f"    Trial #{trial.number}: 得分={score:.4f}, 夏普={avg_sharpe:.2f}, "
          f"收益={avg_return:.1f}%, 回撤={avg_dd:.1f}%, 胜率={avg_wr:.1%}, "
          f"维度={len(enabled_dims)}/6 ({','.join(enabled_dims)}) ({elapsed:.0f}秒)", flush=True)

    return score


def run_baseline_all_on():
    """运行基线回测（全维度开启 = 当前默认）"""
    print(f"\n  [基线] 运行全维度开启回测...")
    macro_config = {f"macro_enable_{d}": True for d in DIMENSIONS}
    symbols = ["BTC", "ETH", "SOL"]
    baseline_scores = {}

    for symbol in symbols:
        df = load_klines(symbol)
        if df is None:
            continue
        result = run_backtest_with_config(symbol, df, macro_config)

        sharpe = compute_sharpe_from_trades(result.all_trades)
        n_trades = len(result.all_trades)
        win_rate = sum(1 for t in result.all_trades if t.pnl_pct > 0) / n_trades if n_trades > 0 else 0
        total_ret = sum(t.pnl_pct for t in result.all_trades)
        max_loss = min((t.pnl_pct for t in result.all_trades), default=0)
        max_dd = abs(max_loss) if max_loss < 0 else 0

        baseline_scores[symbol] = {
            "sharpe": sharpe,
            "return": total_ret,
            "drawdown": max_dd,
            "trades": n_trades,
            "win_rate": win_rate,
        }
        print(f"    {symbol}: 夏普={sharpe:.2f}, 收益={total_ret:.1f}%, 回撤={max_dd:.1f}%, 胜率={win_rate:.1%}, 交易={n_trades}")

    avg_sharpe = np.mean([s["sharpe"] for s in baseline_scores.values()])
    avg_return = np.mean([s["return"] for s in baseline_scores.values()])
    avg_dd = np.mean([s["drawdown"] for s in baseline_scores.values()])
    baseline_score = avg_sharpe + 0.001 * avg_return - 0.02 * avg_dd
    print(f"    基线综合得分: {baseline_score:.4f}")

    return baseline_score, baseline_scores


def run_baseline_no_macro():
    """运行无宏观特征基线（macro 模块完全禁用）"""
    print(f"\n  [基线] 运行无宏观特征回测 (baseline-v1 等效)...")
    # 全部维度关闭 = 等效于不启用 macro 模块
    macro_config = {f"macro_enable_{d}": False for d in DIMENSIONS}
    symbols = ["BTC", "ETH", "SOL"]
    baseline_scores = {}

    for symbol in symbols:
        df = load_klines(symbol)
        if df is None:
            continue
        result = run_backtest_with_config(symbol, df, macro_config)

        sharpe = compute_sharpe_from_trades(result.all_trades)
        n_trades = len(result.all_trades)
        win_rate = sum(1 for t in result.all_trades if t.pnl_pct > 0) / n_trades if n_trades > 0 else 0
        total_ret = sum(t.pnl_pct for t in result.all_trades)
        max_loss = min((t.pnl_pct for t in result.all_trades), default=0)
        max_dd = abs(max_loss) if max_loss < 0 else 0

        baseline_scores[symbol] = {
            "sharpe": sharpe,
            "return": total_ret,
            "drawdown": max_dd,
            "trades": n_trades,
            "win_rate": win_rate,
        }
        print(f"    {symbol}: 夏普={sharpe:.2f}, 收益={total_ret:.1f}%, 回撤={max_dd:.1f}%, 胜率={win_rate:.1%}, 交易={n_trades}")

    avg_sharpe = np.mean([s["sharpe"] for s in baseline_scores.values()])
    avg_return = np.mean([s["return"] for s in baseline_scores.values()])
    avg_dd = np.mean([s["drawdown"] for s in baseline_scores.values()])
    baseline_score = avg_sharpe + 0.001 * avg_return - 0.02 * avg_dd
    print(f"    无宏观基线综合得分: {baseline_score:.4f}")

    return baseline_score, baseline_scores


def run_holdout(best_macro_config):
    """用最后 20% 数据做 hold-out 验证"""
    print(f"\n  [Hold-out] 用最后 20% 数据独立验证最优维度组合...")
    holdout_results = {}

    for symbol in ["BTC", "ETH", "SOL"]:
        df = load_klines(symbol)
        if df is None or len(df) < 800:
            continue

        split_idx = int(len(df) * 0.8)
        holdout_df = df.iloc[split_idx:].copy()

        if len(holdout_df) < 200:
            continue

        try:
            result = run_backtest_with_config(symbol, holdout_df, best_macro_config, n_folds=2)
            sharpe = compute_sharpe_from_trades(result.all_trades)
            n_trades = len(result.all_trades)
            win_rate = sum(1 for t in result.all_trades if t.pnl_pct > 0) / n_trades if n_trades > 0 else 0
            total_ret = sum(t.pnl_pct for t in result.all_trades)

            holdout_results[symbol] = {
                "sharpe": sharpe,
                "return": total_ret,
                "win_rate": win_rate,
                "trades": n_trades,
            }
            print(f"    {symbol}: 夏普={sharpe:.2f}, 收益={total_ret:.1f}%, 胜率={win_rate:.1%}, 交易={n_trades}")
        except Exception as e:
            print(f"    {symbol}: hold-out 失败: {e}")

    return holdout_results


def main():
    print("=" * 80)
    print("  宏观特征维度子集贝叶斯优化")
    print("  搜索空间：6 个维度启用/禁用 (2^6=64 种组合)")
    print("=" * 80)

    # 预加载 K 线数据
    print("\n  [准备] 预加载 K 线数据...")
    for sym in ["BTC", "ETH", "SOL"]:
        df = load_klines(sym)
        if df is not None:
            print(f"    {sym}: {len(df)} bars")
    get_ref_df()

    # 基线1：无宏观特征（等效 baseline-v1）
    no_macro_score, no_macro_scores = run_baseline_no_macro()

    # 基线2：全维度开启（当前 v2-macro）
    all_on_score, all_on_scores = run_baseline_all_on()

    # 优化
    n_trials = 25
    print(f"\n  [优化] 开始贝叶斯搜索（{n_trials} trials）...")
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    t0 = time.time()
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    elapsed = time.time() - t0

    best = study.best_trial
    print(f"\n  优化完成！耗时: {elapsed:.0f}秒")
    print(f"\n  最优试验 #{best.number}:")
    print(f"    综合得分: {best.value:.4f}")
    print(f"    无宏观基线得分: {no_macro_score:.4f}")
    print(f"    全维度基线得分: {all_on_score:.4f}")
    print(f"    平均夏普: {best.user_attrs.get('avg_sharpe', 0):.4f}")
    print(f"    平均收益: {best.user_attrs.get('avg_return', 0):.4f}%")
    print(f"    平均回撤: {best.user_attrs.get('avg_drawdown', 0):.4f}%")
    print(f"    平均胜率: {best.user_attrs.get('avg_win_rate', 0):.4f}")
    print(f"    启用维度: {best.user_attrs.get('enabled_dims', [])}")
    print(f"    维度数: {best.user_attrs.get('n_enabled', 0)}/6")

    print(f"\n  最优维度开关：")
    for dim in DIMENSIONS:
        key = f"macro_enable_{dim}"
        val = best.params.get(key, True)
        print(f"    {key}: {val}")

    # 对比
    improvement_vs_no_macro = best.value - no_macro_score
    improvement_vs_all_on = best.value - all_on_score
    print(f"\n  对比无宏观基线: {improvement_vs_no_macro:+.4f}")
    print(f"  对比全维度基线: {improvement_vs_all_on:+.4f}")

    # Hold-out 验证（仅当优于无宏观基线时）
    if improvement_vs_no_macro > 0:
        best_macro_config = {f"macro_enable_{d}": best.params[f"macro_enable_{d}"] for d in DIMENSIONS}
        holdout_results = run_holdout(best_macro_config)

        # 保存结果
        output = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "no_macro_baseline_score": no_macro_score,
            "all_on_baseline_score": all_on_score,
            "best_score": best.value,
            "improvement_vs_no_macro": improvement_vs_no_macro,
            "improvement_vs_all_on": improvement_vs_all_on,
            "best_macro_config": best_macro_config,
            "best_enabled_dims": best.user_attrs.get("enabled_dims", []),
            "best_user_attrs": {k: v for k, v in best.user_attrs.items()},
            "no_macro_scores": no_macro_scores,
            "all_on_scores": all_on_scores,
            "holdout_results": holdout_results,
            "all_trials": [
                {
                    "number": t.number,
                    "value": t.value,
                    "params": t.params,
                    "user_attrs": t.user_attrs,
                }
                for t in study.trials
            ],
        }

        output_path = os.path.join(SCRIPT_DIR, "..", "..", "..", "data", "baseline", "macro_bayesian_optimal.json")
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  最优参数已保存: {output_path}")

        # 判断是否可落地
        if improvement_vs_no_macro > 0.1 and improvement_vs_all_on > 0:
            print(f"\n  ✓ 宏观特征最优子集通过验证，可进入实盘配置")
            print(f"    启用维度: {best.user_attrs.get('enabled_dims', [])}")
            print(f"    下一步：用最优子集跑 9 币种 5 折完整回测，与 baseline-v1 对比")
        else:
            print(f"\n  △ 最优子集优于全维度但优势有限，建议进一步分析")
    else:
        print(f"\n  ✗ 最优子集未超过无宏观基线，宏观特征暂不建议启用")
        # 仍然保存结果供分析
        output = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "no_macro_baseline_score": no_macro_score,
            "all_on_baseline_score": all_on_score,
            "best_score": best.value,
            "improvement_vs_no_macro": improvement_vs_no_macro,
            "best_macro_config": {f"macro_enable_{d}": best.params.get(f"macro_enable_{d}", True) for d in DIMENSIONS},
            "all_trials": [
                {
                    "number": t.number,
                    "value": t.value,
                    "params": t.params,
                    "user_attrs": t.user_attrs,
                }
                for t in study.trials
            ],
        }
        output_path = os.path.join(SCRIPT_DIR, "..", "..", "..", "data", "baseline", "macro_bayesian_optimal.json")
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  结果已保存: {output_path}")

    print("=" * 80)


if __name__ == "__main__":
    main()
